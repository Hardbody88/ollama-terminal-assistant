# Ollama Terminal Assistant 🤖

**Interact with your terminal using natural language!** This Python CLI tool acts as an intelligent assistant, leveraging the power of local Ollama models to understand your requests, translate them into appropriate shell commands for your OS, and execute them safely with your explicit, step-by-step confirmation. Features automatic error analysis and correction suggestions.

---

## ✨ Key Features

*   **🗣️ Natural Language Interface:** Talk to your terminal naturally (e.g., "show me disk space," "list python files modified today," "what's my IP address?").
*   **🧠 Powered by Local AI:** Uses Ollama and your chosen local models, keeping your data private.
*   **🌐 Cross-Platform Aware:** Detects your OS (Linux, macOS, Windows) and instructs the AI to generate compatible commands.
*   **✅ Step-by-Step Confirmation:** **Crucially, no command runs automatically.** You review and confirm (`Enter`) or skip (`N`) *each individual command* before execution.
*   **💡 Intelligent Suggestions:** Provides AI-generated explanations (`What it does`) and reasoning (`Why these commands`) for proposed actions.
*   **⁉️ Clarification Requests:** If your request is ambiguous or unsafe, the AI will ask for clarification instead of guessing.
*   **🛠️ Automatic Error Handling:** If a confirmed command fails, the assistant automatically sends the error details back to the AI, requesting analysis and potential fixes (e.g., correcting typos, suggesting `sudo`, advising on missing packages).
*   **🔄 Context-Aware:** Remembers the conversation history, including previous command outputs and errors, for more accurate follow-up requests.
*   **⚙️ Configurable:** Set Ollama model, URL, and error retry limits via environment variables.
*   **🎨 Rich Output:** Uses the `rich` library (optional) for a formatted and easy-to-read terminal experience.

---

## 🚀 Why Use This?

*   **Learn Shell Commands:** See the commands generated from your natural language requests.
*   **Reduce Tedium:** Automate simple or slightly complex terminal tasks without recalling exact syntax.
*   **Safety Net:** The mandatory confirmation step prevents accidental execution of harmful commands suggested by the AI. The error analysis helps troubleshoot common issues.
*   **Privacy:** Your interaction stays local via Ollama.

---

## 📋 Prerequisites

*   **Ollama:** Must be installed and running locally. Download from [ollama.com](https://ollama.com/).
*   **Ollama Model:** A capable **instruction-following model** is required. Size matters for reliability.
    *   **Recommended:** `qwen3:4b`, `deepcoder:1.5b` (or larger variants).
    *   Get a model: `ollama run qwen3:8b` (replace model name if needed).
    *   *Note:* Smaller models (< 7B) may struggle significantly with the required JSON formatting and complex instructions.
*   **Python:** Version 3.7+ recommended.
*   **pip:** Python package installer.

---

## ⚙️ Installation

*   **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(This installs `requests` and optionally `rich`)*

---

## 🔧 Configuration

Configure the assistant using environment variables (optional):

*   **`OLLAMA_MODEL`**: Specify the Ollama model to use.
    *   Default: `qwen3:8b` (or as set in the script)
    *   Example: `export OLLAMA_MODEL="mistral:7b"`
*   **`OLLAMA_BASE_URL`**: Your Ollama instance URL if not default.
    *   Default: `http://localhost:11434`
    *   Example: `export OLLAMA_BASE_URL="http://192.168.1.100:11434"`
*   **`MAX_ERROR_RETRY`**: Max auto-retries asking AI for fixes after a command error.
    *   Default: `2`
    *   Example: `export MAX_ERROR_RETRY=1`

*(Set these in your shell profile like `.bashrc` or `.zshrc` for persistence, or just before running)*

---

## ▶️ Usage

1.  **Start Ollama:** Ensure the Ollama application or `ollama serve` is running.
2.  **Run the Assistant:**
    ```bash
    python ollama_terminal.py
    ```
3.  **Interact:**
    *   At the `You:` prompt, type your request in natural language (e.g., "list text files", "check free memory", "create a directory called temp").
    *   The AI will respond, potentially showing:
        *   `Reason`: Why it suggests the commands.
        *   `Explanation`: What the commands do.
        *   `Question`: If it needs more information from you.
        *   `Proposed Command(s)`: One or more commands to achieve your goal.
    *   **Confirmation:** For **each** proposed command, you'll be asked:
        `Execute command X/Y? [Enter=Yes, N=No]:`
        *   Press `Enter` **only** if you understand and approve the command.
        *   Type `n` (or `N`) and press `Enter` to **skip** that specific command.
        *   Any other input also skips the command (safety default).
    *   **Execution & Feedback:** Confirmed commands run. Output (stdout/stderr) or skip/error messages are displayed and fed back into the AI's context.
    *   **Error Recovery:** If a command fails, the assistant will automatically ask the AI for advice (up to `MAX_ERROR_RETRY` times) before prompting you again.
4.  **Exit:** Type `exit` or `quit`, or press `Ctrl+C`.

---

## 💡 How It Works

1.  **OS Detection:** Identifies the host OS (Linux/macOS/Windows) for context.
2.  **System Prompt:** Initializes the conversation with Ollama using a detailed prompt outlining its role, the detected OS, JSON output requirements (`commands`, `reason`, `explanation`, `question`), and error handling rules.
3.  **User Request:** Takes your natural language input.
4.  **API Call:** Sends the full conversation history (including previous results/errors) and your new request to the Ollama `/api/chat` endpoint.
5.  **JSON Parsing:** Parses Ollama's structured JSON response.
6.  **Display AI Thoughts:** Shows any `reason`, `explanation`, or `question` provided by the AI.
7.  **Command Loop:** If commands were suggested, it iterates through them one by one.
8.  **User Confirmation:** Prompts for explicit `Enter` / `N` confirmation for each command.
9.  **Execution / Skip:** Runs confirmed commands via `subprocess.run(shell=True, ...)` or records skips.
10. **Feedback Loop:** Captures command output (stdout/stderr/exit code). This result (or skip status) is formatted and added to the history as a "user" message, informing the AI about the outcome.
11. **Error Retry:** If a command fails, the error feedback is sent, and the script automatically asks Ollama for analysis/correction (steps 4-10 repeat) up to `MAX_ERROR_RETRY` times.

---

## ⚠️ Security Warning: Your Confirmation Matters!

This tool executes shell commands suggested by an AI **only after you explicitly confirm each one**. While powerful, this requires careful attention:

*   **`shell=True` Usage:** Commands are executed using `subprocess.run(shell=True, ...)`. This allows complex commands (pipes `|`, redirects `>`, etc.) suggested by the AI but means the command string is interpreted directly by your system's shell (like Bash, Zsh, Cmd, PowerShell).
*   **Review Before Executing:** **ALWAYS CAREFULLY READ AND UNDERSTAND THE COMMAND** shown at the `Execute? [Enter=Yes, N=No]:` prompt before pressing Enter.
*   **Potential Risks:** Mistakenly confirming a harmful command suggested by the AI (e.g., `rm -rf /`, unintended data modification, `sudo` misuse) could have serious consequences. The AI might misunderstand or generate incorrect commands.
*   **Your Responsibility:** The confirmation step is the primary safety mechanism. **You are responsible for vetting the commands you choose to execute.** If unsure, **always type `N` to skip.**
