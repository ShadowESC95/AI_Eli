#!/usr/bin/env python3
"""
ELI Terminal Interface - No GUI dependencies needed
"""

import sys
import os
import readline  # For better input handling
import time
import json
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Try to import enhanced components, fall back to original
try:
    from eli_tools.router_enhanced import route
    from eli_tools.compat import execute
    print("✅ Using enhanced router and executor")
    ENHANCED = True
except ImportError:
    try:
        from eli_tools.router import route
        from eli_tools.compat import execute
        print("✅ Using original router and executor")
        ENHANCED = False
    except ImportError as e:
        print(f"❌ Failed to import ELI tools: {e}")
        sys.exit(1)

class ELITerminal:
    def __init__(self):
        self.history = []
        self.memory_file = "eli_terminal_history.json"
        self.load_history()
        
        # Colors for terminal (ANSI escape codes)
        self.COLORS = {
            'RESET': '\033[0m',
            'BOLD': '\033[1m',
            'RED': '\033[91m',
            'GREEN': '\033[92m',
            'YELLOW': '\033[93m',
            'BLUE': '\033[94m',
            'MAGENTA': '\033[95m',
            'CYAN': '\033[96m',
            'WHITE': '\033[97m',
            'GRAY': '\033[90m',
        }
    
    def colorize(self, text, color):
        """Add color to text."""
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['RESET']}"
    
    def load_history(self):
        """Load conversation history."""
        try:
            if os.path.exists(self.memory_file):
                with open(self.memory_file, 'r') as f:
                    self.history = json.load(f)
        except:
            self.history = []
    
    def save_history(self):
        """Save conversation history."""
        try:
            with open(self.memory_file, 'w') as f:
                json.dump(self.history[-100:], f, indent=2)  # Keep last 100 entries
        except:
            pass
    
    def clear_screen(self):
        """Clear the terminal screen."""
        os.system('clear' if os.name == 'posix' else 'cls')
    
    def print_header(self):
        """Print the ELI header."""
        self.clear_screen()
        print(self.colorize("╔═══════════════════════════════════════════════════════╗", "CYAN"))
        print(self.colorize("║", "CYAN") + self.colorize("         ELI - Enhanced Linux Assistant         ", "BOLD") + self.colorize("║", "CYAN"))
        print(self.colorize("╠═══════════════════════════════════════════════════════╣", "CYAN"))
        
        if ENHANCED:
            print(self.colorize("║", "CYAN") + self.colorize("  Enhanced Mode: Browser, Spotify, Email, Docs, Memory", "GREEN") + self.colorize("  ║", "CYAN"))
        else:
            print(self.colorize("║", "CYAN") + self.colorize("  Basic Mode: Chat, Math, Time, Files                ", "YELLOW") + self.colorize("  ║", "CYAN"))
        
        print(self.colorize("║", "CYAN") + " " * 55 + self.colorize("║", "CYAN"))
        print(self.colorize("║", "CYAN") + self.colorize("  Type 'help' for commands, 'quit' to exit            ", "GRAY") + self.colorize("  ║", "CYAN"))
        print(self.colorize("╚═══════════════════════════════════════════════════════╝", "CYAN"))
        print()
    
    def print_help(self):
        """Print help information."""
        print(self.colorize("\nAvailable Commands:", "BOLD"))
        print(self.colorize("═" * 50, "CYAN"))
        
        if ENHANCED:
            commands = [
                ("Chat", ["what's up?", "how are you?", "hello"]),
                ("Math", ["2 + 2", "calculate 15 * 3", "what's 5 times 4?"]),
                ("Time/Date", ["what time is it?", "today's date"]),
                ("Apps", ["open browser", "launch spotify", "compose email", "create document"]),
                ("Files", ["list files", "create file.txt", "open file.txt"]),
                ("Memory", ["remember that...", "recall..."]),
                ("Search", ["search web for...", "google..."]),
                ("System", ["run command ls", "change directory to .."]),
                ("Utilities", ["what's the weather?", "show me news"]),
            ]
        else:
            commands = [
                ("Chat", ["what's up?", "how are you?"]),
                ("Math", ["2 + 2", "what's 5 + 3?"]),
                ("Time", ["what time is it?"]),
                ("Files", ["back up my files"]),
            ]
        
        for category, examples in commands:
            print(self.colorize(f"\n{category}:", "YELLOW"))
            for ex in examples:
                print(f"  • {ex}")
        
        print(self.colorize("\nQuick Commands:", "BOLD"))
        print("  • " + self.colorize("help", "GREEN") + " - Show this help")
        print("  • " + self.colorize("history", "GREEN") + " - Show conversation history")
        print("  • " + self.colorize("clear", "GREEN") + " - Clear screen")
        print("  • " + self.colorize("quit", "GREEN") + " or " + self.colorize("exit", "GREEN") + " - Exit ELI")
        print()
    
    def print_result(self, user_input, result):
        """Print the execution result."""
        print()
        print(self.colorize("─" * 60, "GRAY"))
        
        # User input
        print(self.colorize("YOU:", "GREEN") + f" {user_input}")
        
        # Routing info
        if 'routed_action' in result:
            print(self.colorize("ROUTE:", "BLUE") + f" {result['routed_action']}")
        
        # Result
        if result.get('ok', False):
            if 'response' in result:
                print(self.colorize("ELI:", "CYAN") + f" {result['response']}")
            elif 'result' in result:
                print(self.colorize("MATH:", "CYAN") + f" {result['result']}")
            elif 'time' in result:
                print(self.colorize("TIME:", "CYAN") + f" {result['time']}")
            elif 'date' in result:
                print(self.colorize("DATE:", "CYAN") + f" {result['date']}")
            elif 'message' in result:
                print(self.colorize("ELI:", "CYAN") + f" {result['message']}")
            elif 'files' in result:
                files = result['files']
                print(self.colorize("FILES:", "CYAN") + f" {len(files)} files in {result.get('path', '.')}")
                for f in files[:10]:
                    print(f"  • {f}")
                if len(files) > 10:
                    print(f"  ... and {len(files) - 10} more")
            elif 'memories' in result:
                memories = result['memories']
                print(self.colorize("MEMORIES:", "CYAN") + f" {len(memories)} found")
                for m in memories:
                    print(f"  • {m}")
            else:
                print(self.colorize("RESULT:", "CYAN") + f" {result}")
        else:
            print(self.colorize("ERROR:", "RED") + f" {result.get('error', 'Unknown error')}")
        
        print(self.colorize("─" * 60, "GRAY"))
        print()
    
    def handle_special_commands(self, user_input):
        """Handle special terminal commands."""
        user_input_lower = user_input.lower().strip()
        
        if user_input_lower in ['quit', 'exit', 'q']:
            print(self.colorize("\nGoodbye! 👋", "CYAN"))
            self.save_history()
            return True
        
        elif user_input_lower == 'help':
            self.print_help()
            return True
        
        elif user_input_lower == 'history':
            print(self.colorize("\nConversation History:", "BOLD"))
            print(self.colorize("═" * 50, "CYAN"))
            for i, entry in enumerate(self.history[-10:], 1):  # Last 10 entries
                print(f"{i:2}. {entry.get('input', '')[:50]}...")
            print()
            return True
        
        elif user_input_lower == 'clear':
            self.print_header()
            return True
        
        elif user_input_lower == 'enhanced':
            global ENHANCED
            if not ENHANCED:
                print(self.colorize("\nTrying to load enhanced mode...", "YELLOW"))
                try:
                    from eli_tools.router_enhanced import route as route_enhanced
                    from eli_tools.compat import execute as execute_enhanced
                    globals()['route'] = route_enhanced
                    globals()['execute'] = execute_enhanced
                    ENHANCED = True
                    print(self.colorize("✅ Enhanced mode activated!", "GREEN"))
                except ImportError:
                    print(self.colorize("❌ Enhanced modules not available", "RED"))
            else:
                print(self.colorize("✅ Already in enhanced mode", "GREEN"))
            return True
        
        return False
    
    def run(self):
        """Run the terminal interface."""
        self.print_header()
        
        print(self.colorize("Type your command below. Start with:", "GRAY"))
        if ENHANCED:
            print("  • " + self.colorize("'open browser'", "YELLOW") + " - Launch web browser")
            print("  • " + self.colorize("'launch spotify'", "YELLOW") + " - Start Spotify")
            print("  • " + self.colorize("'compose email'", "YELLOW") + " - Write an email")
            print("  • " + self.colorize("'remember that...'", "YELLOW") + " - Store a memory")
        print("  • " + self.colorize("'what's up?'", "YELLOW") + " - Chat with ELI")
        print("  • " + self.colorize("'2 + 2'", "YELLOW") + " - Do math")
        print("  • " + self.colorize("'help'", "YELLOW") + " - Show all commands")
        print()
        
        while True:
            try:
                # Get user input with prompt
                prompt = self.colorize("eli> ", "GREEN")
                user_input = input(prompt).strip()
                
                if not user_input:
                    continue
                
                # Handle special commands
                if self.handle_special_commands(user_input):
                    if user_input.lower() in ['quit', 'exit', 'q']:
                        break
                    continue
                
                # Record in history
                self.history.append({
                    'input': user_input,
                    'timestamp': datetime.now().isoformat()
                })
                
                # Route and execute
                print(self.colorize("⌛ Processing...", "YELLOW"), end='\r')
                
                try:
                    # Route the input
                    routed = route(user_input)
                    action = routed['action']
                    args = routed.get('args', {})
                    
                    # Execute
                    result = execute(action, args)
                    
                    # Add routing info to result
                    result['routed_action'] = action
                    
                    # Print result
                    self.print_result(user_input, result)
                    
                except Exception as e:
                    error_result = {
                        'ok': False,
                        'error': f"Execution error: {str(e)}",
                        'routed_action': 'error'
                    }
                    self.print_result(user_input, error_result)
                
                # Save history periodically
                if len(self.history) % 5 == 0:
                    self.save_history()
                    
            except KeyboardInterrupt:
                print(self.colorize("\n\nUse 'quit' to exit or 'clear' to continue", "YELLOW"))
                continue
            except EOFError:
                print(self.colorize("\n\nGoodbye! 👋", "CYAN"))
                break
        
        self.save_history()

def main():
    """Main entry point."""
    print("Starting ELI Terminal Interface...")
    print("Project root:", os.path.dirname(os.path.abspath(__file__)))
    
    eli = ELITerminal()
    eli.run()

if __name__ == "__main__":
    main()
