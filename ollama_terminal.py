import requests
import subprocess
import json
import sys
import os
import platform
import re

# --- Configuration ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# >>> Use a powerful instruction-following model <
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_API_ENDPOINT = f"{OLLAMA_BASE_URL}/api/chat"
TIMEOUT_SECONDS = 120  # Increased timeout for potentially more complex reasoning
MAX_ERROR_RETRY = 2  # Max times to automatically ask AI for fix after an error in one turn

# --- Rich Integration (Optional but Recommended) ---
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.markdown import Markdown
    console = Console()
    USE_RICH = True
    def print_info(text): console.print(f"[blue]INFO:[/blue] {text}")
    def print_success(text): console.print(f"[green]SUCCESS:[/green] {text}")
    def print_warning(text): console.print(f"[yellow]WARN:[/yellow] {text}")
    def print_error(text): console.print(f"[bold red]ERROR:[/bold red] {text}")
    def print_ai_field(text, title, style="italic dim"): console.print(Panel(f"[{style}]{text}[/{style}]", title=title, border_style="dim"))
    def print_proposed_command(cmd, num=None, total=None):
        title = f"Proposed Command {f'{num}/{total}' if num is not None else ''}"
        console.print(Panel(Syntax(cmd, "bash", theme="default", line_numbers=False), title=title, border_style="cyan", padding=(0, 1)))
    def print_output(text, title, border_style="bright_black"): console.print(Panel(text.strip() if text else "[No Output]", title=title, border_style=border_style))
    def print_user_prompt(): return console.input("[bold magenta]\nYou:[/bold magenta] ")
    def print_raw_assistant(text): console.print(Panel(text, title="Raw Ollama Response", border_style="red", style="dim"))
except ImportError:
    USE_RICH = False
    # Basic print fallbacks
    def print_info(text): print(f"INFO: {text}")
    def print_success(text): print(f"SUCCESS: {text}")
    def print_warning(text): print(f"WARNING: {text}")
    def print_error(text): print(f"ERROR: {text}")
    def print_ai_field(text, title, style="italic dim"): 
        print(f"\n--- {title} ---")
        print(f"{text}")
        print("---" + "-" * len(title) + "---")
    def print_proposed_command(cmd, num=None, total=None):
        title = f"Proposed Command {f'{num}/{total}' if num is not None else ''}"
        print(f"\n--- {title} ---")
        print(f"{cmd}")
        print("---" + "-" * len(title) + "---")
    def print_output(text, title, border_style="bright_black"):
        print(f"\n--- {title} ---")
        print(f"{text.strip() if text else '[No Output]'}")
        print("---" + "-" * len(title) + "---")
    def print_user_prompt(): 
        return input("\nYou: ")
    def print_raw_assistant(text):
        print("\n--- Raw Ollama Response ---")
        print(text)
        print("-------------------------")
    print("Warning: 'rich' library not found. Output formatting will be basic.")

# --- OS Detection & Info ---
def get_os_info():
    """Gathers basic OS information, including a platform type hint."""
    os_info = {}
    os_name = platform.system()
    os_info['system'] = os_name  # e.g., 'Linux', 'Darwin', 'Windows'
    os_info['release'] = platform.release()
    os_info['version'] = platform.version()
    os_info['architecture'] = platform.machine()
    
    if os_name == 'Linux':
        os_info['platform_type'] = 'linux'
        try:
            # Try reading /etc/os-release for distribution info
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        os_info[key.lower()] = value.strip('"')
            dist_name = os_info.get('name', 'Unknown Linux')
            dist_version = os_info.get('version_id', '')
            os_info['details'] = f"{dist_name} {dist_version} (Kernel: {os_info['release']})"
        except Exception:
            os_info['details'] = f"Linux (Kernel: {os_info['release']})"
    elif os_name == 'Darwin':
        os_info['platform_type'] = 'macos'
        os_info['details'] = f"macOS {platform.mac_ver()[0]} (Kernel: {os_info['release']})"
    elif os_name == 'Windows':
        os_info['platform_type'] = 'windows'
        os_info['details'] = f"Windows {os_info['release']} {os_info['version']}"
    else:
        os_info['platform_type'] = 'unknown'
        os_info['details'] = f"{os_info['system']} {os_info['release']}"
    
    # Only return essential details for the prompt
    return {"name": os_name, "details": os_info['details'], "type": os_info['platform_type']}

# --- System Prompt (Enhanced) ---
def create_system_prompt(os_info):
    """Creates the system prompt with OS details and refined JSON instructions."""
    return f"""
You are an AI assistant embedded in a terminal environment.
The current operating system is: **{os_info['details']}** (Type: {os_info['type']}).
Your goal is to translate the user's natural language requests into a sequence of executable shell commands **appropriate for this specific OS ({os_info['name']})**.

RULES:
1.  **Respond ONLY in JSON format.** The JSON object must have these keys:
    *   *`"commands"`*: (list of strings) A list containing zero or more executable shell commands for **{os_info['name']}** to fulfill the request, in order. Mandatory.
    *   *`"reason"`*: (string, optional) Briefly explain *why* these specific commands are suggested, possibly referencing previous context or output.
    *   *`"explanation"`*: (string, optional) Briefly explain *what* the commands do.
    *   *`"question"`*: (string, optional) If you need clarification from the user or cannot fulfill the request safely/clearly, provide your question here. **If you include a question, the "commands" list should usually be empty.**

2.  Each string in the `"commands"` list MUST be a valid shell command for **{os_info['name']}**.
3.  Do NOT include any text outside the JSON structure.
4.  **Handling Errors:** If the user feedback indicates a command failed (non-zero exit code, specific stderr messages like 'command not found'), analyze the error provided in the user message.
    *   If you can suggest a corrected command or sequence, provide it in the `"commands"` list. Use `"reason"` to explain the fix.
    *   If a command was 'not found', suggest the correct installation command for **{os_info['name']}** (e.g., `apt install`, `brew install`, `choco install`, `winget install`). You might put the install command in `"commands"` or explain it in `"reason"`/`"explanation"`.
    *   If you need more information to fix the error, ask using the `"question"` field and set `"commands"` to `[]`.

5.  **Safety:** If a request seems ambiguous, dangerous (e.g., deleting critical files without specifics), or cannot be translated into commands, set `"commands"` to `[]` and explain why in `"reason"` or ask for clarification via `"question"`.

Example Request: "show the time, then list files" (on Linux)
Example Correct JSON Response:
```json
{{
  "commands": ["date", "ls -la"],
  "reason": "User asked for time and then file listing.",
  "explanation": "Displays the current date/time, then lists all files (including hidden) in the current directory."
}}
```

Example Request: "I need to install 'htop'." (on macOS)
Example Correct JSON Response:
```json
{{
  "commands": ["brew install htop"],
  "reason": "User requested installation of 'htop' on macOS.",
  "explanation": "Uses Homebrew (package manager for macOS) to install the 'htop' process viewer."
}}
```

Example User Feedback: "Command `gitt status` failed with exit code 127 and stderr 'bash: gitt: command not found'" (on Linux)
Example Correct JSON Response (asking AI after error):
```json
{{
  "commands": ["git status"],
  "reason": "The previous command 'gitt status' likely had a typo ('gitt' instead of 'git').",
  "explanation": "Checks the status of the current Git repository."
}}
```

Example User Feedback: "Command `apt install cowsay` failed with exit code 100 and stderr 'E: Could not open lock file... Permission denied'" (on Linux)
Example Correct JSON Response (asking AI after error):
```json
{{
  "commands": ["sudo apt install cowsay"],
  "reason": "The previous 'apt install' failed with a permission error, likely requiring administrator privileges.",
  "explanation": "Uses 'sudo' to run 'apt install cowsay' with administrator rights."
}}
```

Example Request: "delete my project" (Ambiguous)
Example Correct JSON Response:
```json
{{
  "commands": [],
  "question": "Which project directory do you want to delete? Please provide the full path for safety."
}}
```
"""

# --- Helper Functions ---
def parse_ollama_json(raw_response):
    """
    Parses Ollama's response, expecting the new JSON structure.
    Returns (commands_list, reason, explanation, question) or (None, None, None, error_message).
    """
    if not raw_response:
        return None, None, None, None, "Ollama returned an empty response."
    
    # Enhanced JSON extraction
    json_str = raw_response.strip()
    match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", json_str, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        # Find the outermost curly braces
        brace_start = json_str.find('{')
        brace_end = json_str.rfind('}')
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            json_str = json_str[brace_start : brace_end + 1]
        # else: pass # Let json.loads try anyway
    
    try:
        data = json.loads(json_str)
        commands = data.get("commands")
        reason = data.get("reason", "")  # Default to empty string
        explanation = data.get("explanation", "")
        question = data.get("question", "")
        
        # Validate 'commands'
        if commands is None:
            return None, reason, explanation, question, "JSON received, but 'commands' key is missing or null."
        if not isinstance(commands, list):
            return None, reason, explanation, question, f"JSON 'commands' value is not a list (got {type(commands)})."
        for i, cmd in enumerate(commands):
            if not isinstance(cmd, str):
                return None, reason, explanation, question, f"Item {i} in 'commands' list is not a string (got {type(cmd)})."
        
        return commands, reason, explanation, question, None
    except json.JSONDecodeError as e:
        # print_raw_assistant(raw_response)  # Uncomment for deep debugging
        return None, None, None, None, f"Failed to decode JSON response: {e}. Raw text was:\n{raw_response}"
    except Exception as e:
        # print_raw_assistant(raw_response)
        return None, None, None, None, f"An unexpected error occurred during JSON parsing: {e}"

def call_ollama(messages):
    """Sends messages to Ollama and returns the assistant's raw response content."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": { "temperature": 0.2 }  # Low temp for consistency
    }
    
    try:
        response = requests.post(OLLAMA_API_ENDPOINT, json=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        
        if "message" in data and "content" in data["message"]:
            return data["message"]["content"]
        elif isinstance(data, dict) and "commands" in data:
            return json.dumps(data)  # Re-serialize if response is the JSON itself
        else:
            print_error(f"Unexpected Ollama response structure: {data}")
            return None
    except requests.exceptions.RequestException as e:
        print_error(f"API call failed: {e}")
        return None
    except json.JSONDecodeError:
        print_error(f"Failed to decode Ollama's top-level JSON response: {response.text}")
        return None
    except KeyError as e:
        print_error(f"Key error in Ollama response: {e} - Response: {data}")
        return None

def run_command(command, os_type):
    """Executes a shell command, handling potential encoding issues."""
    print_info(f"Executing: '{command}'")
    shell_executable = None
    
    # Simple heuristic for shell choice, could be refined
    if os_type == 'windows':
        # Using cmd might be more universally available than powershell initially
        # Can try powershell if cmd fails or based on command content? More complex.
        # shell_executable = 'powershell.exe'  # Alternatively
        pass  # Let subprocess choose default (usually cmd)
    else:  # Linux, macOS
        # Default shell is usually fine (/bin/sh or /bin/bash)
        pass
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            # text=True causes issues with complex encodings sometimes
            check=False,
            encoding=sys.stdout.encoding or 'utf-8',  # Use terminal's encoding
            errors='replace',  # Replace undecodable characters
            executable=shell_executable
        )
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        print_error(f"Failed to execute command: {e}")
        # Return None for stdout/stderr to indicate execution failure
        return None, str(e), 1

# --- Main Execution Loop ---
if __name__ == "__main__":
    current_os_info = get_os_info()
    system_prompt_content = create_system_prompt(current_os_info)
    
    print_info(f"Initializing Ollama Terminal Assistant with model '{OLLAMA_MODEL}'...")
    print_info(f"Detected OS: {current_os_info['details']}")
    print_info(f"Using Ollama instance at: {OLLAMA_BASE_URL}")
    print_info("Type 'exit' or 'quit' to end the session.")
    
    chat_history = [{"role": "system", "content": system_prompt_content}]
    error_retry_count = 0  # Counter for automatic retries after errors
    
    try:
        while True:
            # 1. Get user input (unless recovering from error)
            if error_retry_count == 0:
                try:
                    user_input = print_user_prompt()
                except EOFError:
                    print("\nGoodbye!")
                    break
                
                if not user_input: continue
                if user_input.lower() in ["exit", "quit"]:
                    print("Goodbye!")
                    break
                
                chat_history.append({"role": "user", "content": user_input})
            else:
                # We are in an error recovery attempt
                print_info(f"Asking AI for advice on the previous error (Attempt {error_retry_count}/{MAX_ERROR_RETRY})...")
            
            # 2. Get suggestion(s) from Ollama
            raw_ollama_response = call_ollama(chat_history)
            if raw_ollama_response is None:
                # API call failed, reset error count if we were retrying
                error_retry_count = 0
                # Decide whether to pop the last *user* message or the *error* message
                # Simple approach: just continue and let user try again
                continue
            
            # 3. Parse the JSON response
            commands, reason, explanation, question, error = parse_ollama_json(raw_ollama_response)
            if commands is None:  # Parsing failed
                print_warning("Ollama response was not in the expected JSON format.")
                if error:  # The error message from parser
                    print_error(f"Details: {error}")
                if raw_ollama_response: print_raw_assistant(raw_ollama_response)
                # Add raw response to history so model sees its failure
                chat_history.append({"role": "assistant", "content": raw_ollama_response or ""})
                error_retry_count = 0  # Failed parse, reset error state
                continue
            
            # Successfully parsed, add valid assistant response to history
            chat_history.append({"role": "assistant", "content": raw_ollama_response})
            
            # Display AI reasoning/explanation/question
            if reason: print_ai_field(reason, "Reason")
            if explanation: print_ai_field(explanation, "Explanation") 
            if question:
                print_ai_field(question, "Question from Assistant", style="bold yellow")
                error_retry_count = 0  # AI asked a question, stop error recovery, wait for user
                continue  # Go back to prompt user for response to the question
            
            # 4. Handle empty command list (AI decided not to run anything)
            if not commands:
                print_info("Ollama suggests no commands for this request.")
                no_command_feedback = "Assistant indicated no commands should be run for the last request."
                chat_history.append({"role": "user", "content": no_command_feedback})
                error_retry_count = 0  # No commands, so no error possible here
                continue
            
            # 5. Process the list of commands
            num_commands = len(commands)
            command_failed = False  # Flag if any command in the sequence fails
            
            for i, command in enumerate(commands):
                step_num = i + 1
                print_proposed_command(command, step_num, num_commands)
                
                # Confirmation Step
                try:
                    confirm_input = input(f"Execute command {step_num}/{num_commands}? [Enter=Yes, N=No]: ").lower().strip()
                except EOFError:
                    print("\nOperation cancelled. Goodbye!")
                    sys.exit(0)
                
                if confirm_input == "":  # Execute on Enter
                    stdout, stderr, returncode = run_command(command, current_os_info['type'])
                    
                    # Create feedback message FIRST
                    exec_result = (
                        f"User confirmed and executed command {step_num}/{num_commands}: `{command}`\n"
                        f"Exit Code: {returncode}\n"
                    )
                    # Handle None stdout/stderr if run_command failed internally
                    exec_result += f"STDOUT:\n```\n{(stdout or '').strip()}\n```\n"
                    exec_result += f"STDERR:\n```\n{(stderr or '').strip()}\n```"
                    
                    # Display results AFTER preparing feedback
                    if returncode == 0:
                        print_success(f"Command {step_num}/{num_commands} finished successfully (Exit Code 0).")
                        if stdout: print_output(stdout, f"Stdout (Cmd {step_num})", border_style="green")
                        if stderr: print_output(stderr, f"Stderr (Cmd {step_num})", border_style="yellow")  # Stderr isn't always an error
                        if not stdout and not stderr: print_info(f"Command {step_num}/{num_commands} produced no output.")
                        error_retry_count = 0  # Success, reset error counter
                    else:
                        print_error(f"Command {step_num}/{num_commands} failed (Exit Code {returncode}).")
                        if stdout: print_output(stdout, f"Stdout (Cmd {step_num})", border_style="yellow")  # Show stdout even on failure
                        if stderr: print_output(stderr, f"Stderr (Cmd {step_num})", border_style="red")
                        else: print_warning("Command failed but produced no stderr output.")
                        command_failed = True  # Mark that a failure occurred
                    
                    # Add execution result feedback to history
                    chat_history.append({"role": "user", "content": exec_result.strip()})
                    
                    # If command failed, check retry limit and break inner loop to ask AI
                    if command_failed:
                        error_retry_count += 1
                        if error_retry_count > MAX_ERROR_RETRY:
                            print_error(f"Max error retry limit ({MAX_ERROR_RETRY}) reached. Please try a different approach.")
                            error_retry_count = 0  # Reset for next user input
                        break  # Break command loop, trigger AI error analysis in outer loop
                else:  # Skip command (N or other input)
                    print_warning(f"Command {step_num}/{num_commands} skipped by user.")
                    skip_feedback = f"User skipped command {step_num}/{num_commands}: `{command}`"
                    chat_history.append({"role": "user", "content": skip_feedback})
                    error_retry_count = 0  # User skipped, not an error state
                    # Optional: Ask if user wants to skip remaining commands in sequence?
                    # confirm_skip_rest = input("Skip remaining commands in this sequence? [y/N]: ").lower().strip()
                    # if confirm_skip_rest == 'y':
                    #    break  # Break command loop
            
            # After loop: if a command failed and we haven't exceeded retries,
            # the outer loop will continue and immediately call Ollama again.
            # If all commands succeeded OR retries were exceeded OR user skipped,
            # reset error count and wait for next user input.
            if not command_failed:
                error_retry_count = 0
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")
    finally:
        pass  # Any cleanup if needed
