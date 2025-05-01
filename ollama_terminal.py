import requests
import subprocess
import json
import sys
import os
import platform
import re

# --- Configuration ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b") # Use a capable model (llama3, mistral, etc.)
OLLAMA_API_ENDPOINT = f"{OLLAMA_BASE_URL}/api/chat"
TIMEOUT_SECONDS = 90 # Increased timeout slightly for potentially longer generations

# Attempt to use rich for better output
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    console = Console()
    USE_RICH = True
    def print_info(text): console.print(f"[bold blue]INFO:[/bold blue] {text}")
    def print_success(text): console.print(f"[bold green]SUCCESS:[/bold green] {text}")
    def print_warning(text): console.print(f"[bold yellow]WARN:[/bold yellow] {text}")
    def print_error(text): console.print(f"[bold red]ERROR:[/bold red] {text}")
    def print_command_explanation(exp, title="Ollama Suggestion"): console.print(Panel(f"[italic]Explanation: {exp}[/italic]", title=title, border_style="dim"))
    def print_proposed_command(cmd, num=None, total=None):
        title = f"Proposed Command {f'{num}/{total}' if num and total else ''}"
        console.print(Panel(Syntax(cmd, "bash", theme="default", line_numbers=False), title=title, border_style="cyan", padding=(0, 1)))
    def print_output(text, title, border_style="bright_black"): console.print(Panel(text.strip() if text else "[No Output]", title=title, border_style=border_style))
    def print_user_prompt(): return console.input("[bold magenta]You:[/bold magenta] ")
    def print_raw_assistant(text): console.print(f"🤖 [dim]Raw Ollama:[/dim]\n{text}")

except ImportError:
    USE_RICH = False
    def print_info(text): print(f"INFO: {text}")
    def print_success(text): print(f"SUCCESS: {text}")
    def print_warning(text): print(f"WARN: {text}")
    def print_error(text): print(f"ERROR: {text}")
    def print_command_explanation(exp, title="Ollama Suggestion"): print(f"\nINFO: Ollama explanation: {exp}")
    def print_proposed_command(cmd, num=None, total=None):
        prefix = f"COMMAND {f'{num}/{total}' if num and total else ''}: "
        print(f"\n{prefix}{cmd}")
    def print_output(text, title, border_style=None): print(f"{title}:\n------\n{text.strip() if text else '[No Output]'}\n------")
    def print_user_prompt(): return input("\nYou: ")
    def print_raw_assistant(text): print(f"DEBUG: Raw Ollama output:\n{text}")

# --- OS Detection ---
def get_os_info():
    """Gathers basic OS information."""
    os_info = {}
    os_info['system'] = platform.system()
    os_info['release'] = platform.release()
    os_info['version'] = platform.version()
    if os_info['system'] == 'Linux':
        try:
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        os_info[key.lower()] = value.strip('"')
            dist_name = os_info.get('name', 'Unknown Linux')
            dist_version = os_info.get('version_id', '')
            return f"{dist_name} {dist_version} (Kernel: {os_info['release']})"
        except Exception:
             return f"Linux (Kernel: {os_info['release']})"
    elif os_info['system'] == 'Darwin':
        return f"macOS {platform.mac_ver()[0]} (Kernel: {os_info['release']})"
    else:
        return f"{os_info['system']} {os_info['release']}"

# --- System Prompt (Modified for list of commands) ---
def create_system_prompt(os_details):
    """Creates the system prompt, asking for a list of commands in JSON."""
    return f"""
You are an AI assistant embedded in a terminal environment.
The current operating system is: **{os_details}**

Your goal is to translate the user's natural language requests into a sequence of executable shell commands relevant to this OS.

RULES:
1.  **Respond ONLY in JSON format.** The JSON object must have these keys:
    *   `"commands"`: (list of strings) A list containing one or more executable shell commands needed to fulfill the user's request, in the correct order. This is mandatory. If only one command is needed, return a list with a single element.
    *   `"explanation"`: (string) A brief explanation of the overall goal or purpose of the command(s). This is optional but helpful.
2.  Each string in the `"commands"` list MUST be a valid shell command executable in the specified OS environment ({os_details}).
3.  Do NOT include any text outside the JSON structure.
4.  If the user's request is unclear, cannot be translated into commands, or is unsafe, set the `"commands"` list to empty (`[]`) and provide the reason in the `"explanation"`.
5.  Base your command suggestions on the provided OS ({os_details}) and the conversation history, including the output of previously executed commands.

Example Request: "show the time, then list files"
Example Correct JSON Response:
```json
{{
  "commands": ["date", "ls -l"],
  "explanation": "Displays the current date/time, then lists files in the current directory."
}}
```

Example Request: "what is my ip address?" (Assuming Linux)
Example Correct JSON Response:
```json
{{
  "commands": ["ip addr show"],
  "explanation": "Displays network interface configuration and IP addresses."
}}
```

Example Request: "update my system" (Ambiguous/Potentially complex)
Example Correct JSON Response:
```json
{{
  "commands": [],
  "explanation": "System updates can involve multiple steps and require supervision. Please specify the package manager (e.g., apt, yum) or use the standard update procedures for your system."
}}
```
"""

# --- Helper Functions ---

def parse_ollama_json(raw_response):
    """
    Attempts to parse Ollama's response as JSON, expecting 'commands' (list) and 'explanation'.
    Returns (commands_list, explanation) or (None, error_message).
    """
    if not raw_response:
        return None, "Ollama returned an empty response."

    # Find JSON block, handling potential markdown wrappers
    json_str = raw_response.strip()
    match = re.search(r"```json\s*([\s\S]*?)\s*```", json_str, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        # Simple brace finding as fallback
        brace_start = json_str.find('{')
        brace_end = json_str.rfind('}')
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            json_str = json_str[brace_start : brace_end + 1]
        else:
            # Attempt parsing directly even without obvious markers
            pass # Let the json.loads handle potential errors

    try:
        data = json.loads(json_str)
        commands = data.get("commands")
        explanation = data.get("explanation", "")

        # Validate 'commands'
        if commands is None:
            return None, explanation or "JSON received, but 'commands' key is missing or null."
        if not isinstance(commands, list):
            return None, f"JSON received, but 'commands' value is not a list (got {type(commands)})."
        # Validate elements within 'commands' list
        for i, cmd in enumerate(commands):
            if not isinstance(cmd, str):
                return None, f"JSON received, but item {i} in 'commands' list is not a string (got {type(cmd)})."

        return commands, explanation

    except json.JSONDecodeError as e:
        print_raw_assistant(raw_response) # Show what we tried to parse
        return None, f"Failed to decode JSON response: {e}. Raw response was:\n{raw_response}"
    except Exception as e:
        print_raw_assistant(raw_response)
        return None, f"An unexpected error occurred during JSON parsing: {e}"


def call_ollama(messages):
    """Sends messages to Ollama and returns the assistant's raw response content."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {
             "temperature": 0.2 # Keep low temp for structured output
        }
    }
    try:
        response = requests.post(OLLAMA_API_ENDPOINT, json=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()

        if "message" in data and "content" in data["message"]:
             return data["message"]["content"]
        elif isinstance(data, dict) and "commands" in data: # Handle case where response *is* the JSON
             return json.dumps(data)
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


def run_command(command):
    """Executes a shell command and captures its output."""
    print_info(f"Executing: '{command}'")
    try:
        result = subprocess.run(
            command,
            shell=True, # Be cautious, relies on user confirmation
            capture_output=True,
            text=True,
            check=False,
            encoding='utf-8',
            errors='replace'
        )
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        print_error(f"Failed to execute command: {e}")
        return None, str(e), 1


# --- Main Execution ---
if __name__ == "__main__":
    current_os_info = get_os_info()
    system_prompt_content = create_system_prompt(current_os_info)

    print_info(f"Initializing Ollama Terminal Assistant with model '{OLLAMA_MODEL}'...")
    print_info(f"Detected OS: {current_os_info}")
    print_info(f"Using Ollama instance at: {OLLAMA_BASE_URL}")
    print_info("Type 'exit' or 'quit' to end the session.")

    chat_history = [{"role": "system", "content": system_prompt_content}]

    try:
        while True:
            # 1. Get user input
            try:
                user_input = print_user_prompt()
            except EOFError:
                print("\nGoodbye!")
                break

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break

            chat_history.append({"role": "user", "content": user_input})

            # 2. Get command suggestion(s) from Ollama
            print_info("Asking Ollama for command(s)...")
            raw_ollama_response = call_ollama(chat_history)

            if raw_ollama_response is None:
                chat_history.pop() # Remove failed user message
                continue

            # 3. Parse the JSON response
            proposed_commands, explanation = parse_ollama_json(raw_ollama_response)

            if proposed_commands is None:
                print_warning("Ollama did not provide valid commands in the expected JSON format.")
                if explanation: # If parser returned an error message
                    print_error(f"Details: {explanation}")
                if raw_ollama_response: print_raw_assistant(raw_ollama_response)
                # Add raw response to history so model sees its failure
                chat_history.append({"role": "assistant", "content": raw_ollama_response or ""})
                continue

            # Add assistant's valid structured response to history *once*
            chat_history.append({"role": "assistant", "content": raw_ollama_response})

            # 4. Handle empty command list (Ollama indicating "don't run")
            if not proposed_commands:
                 print_warning("Ollama suggests not running any commands for this request.")
                 if explanation:
                     print_command_explanation(explanation, title="Reason")
                 # Add feedback that no commands were run
                 no_command_feedback = "Assistant indicated no commands should be run."
                 chat_history.append({"role": "user", "content": no_command_feedback})
                 continue

            # 5. Process the list of commands
            num_commands = len(proposed_commands)
            if explanation:
                 print_command_explanation(explanation)

            all_skipped = True # Track if user skips all commands in a multi-step request

            for i, command in enumerate(proposed_commands):
                step_num = i + 1
                print_proposed_command(command, step_num, num_commands)

                # Confirmation Step (Enter = Yes, N = No)
                try:
                    confirm_input = input(f"Execute command {step_num}/{num_commands}? [Enter=Yes, N=No]: ").lower().strip()
                except EOFError:
                     print("\nOperation cancelled. Goodbye!")
                     sys.exit(0) # Exit cleanly if Ctrl+D during confirm

                if confirm_input == "": # Execute on Enter
                    all_skipped = False # At least one command was not skipped
                    stdout, stderr, returncode = run_command(command)

                    # Display output
                    print_success(f"Command {step_num}/{num_commands} finished with exit code {returncode}")
                    if stdout:
                        print_output(stdout, f"Stdout (Cmd {step_num})", border_style="green" if returncode == 0 else "yellow")
                    if stderr:
                        print_output(stderr, f"Stderr (Cmd {step_num})", border_style="red" if returncode != 0 else "yellow")
                    if not stdout and not stderr and returncode == 0:
                        print_info(f"Command {step_num}/{num_commands} produced no output.")

                    # Prepare feedback for this command
                    output_feedback = (
                        f"User confirmed and executed command {step_num}/{num_commands}: `{command}`\n"
                        f"Exit Code: {returncode}\n"
                        f"STDOUT:\n```\n{stdout.strip()}\n```\n"
                        f"STDERR:\n```\n{stderr.strip()}\n```"
                    )
                    chat_history.append({"role": "user", "content": output_feedback.strip()})

                    # Optional: Stop sequence if a command fails?
                    # if returncode != 0:
                    #     print_warning(f"Command {step_num} failed. Stopping sequence.")
                    #     break

                elif confirm_input == 'n': # Skip on N
                    print_warning(f"Command {step_num}/{num_commands} skipped by user.")
                    skip_feedback = f"User skipped command {step_num}/{num_commands}: `{command}`"
                    chat_history.append({"role": "user", "content": skip_feedback})
                else: # Skip on any other input for safety
                    print_warning(f"Unrecognized input '{confirm_input}'. Command {step_num}/{num_commands} skipped.")
                    skip_feedback = f"User skipped command {step_num}/{num_commands} due to unrecognized input: `{command}`"
                    chat_history.append({"role": "user", "content": skip_feedback})


            # Optional: Add summary feedback if all proposed commands were skipped
            # if all_skipped and num_commands > 0:
            #    all_skip_summary = f"User skipped all {num_commands} proposed commands for the initial request."
            #    chat_history.append({"role": "user", "content": all_skip_summary})


    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")
    finally:
        pass
