"""Fast chat model integration for ELI with Ollama - optimized for speed"""

import os
import sys
import random
import threading
import queue
import time

def _env_timeout(default: int = 120) -> int:
    """Read timeout (seconds) from env vars. Digits-only accepted."""
    for k in ("ELI_CHAT_TIMEOUT", "ELI_HTTP_TIMEOUT", "ELI_TIMEOUT", "OLLAMA_TIMEOUT"):
        v = os.environ.get(k)
        if v and v.strip().isdigit():
            return int(v.strip())
    return int(default)


class FastChatModel:
    def __init__(self):
        self.model_type = self.detect_model()
        from eli_tools import config as eli_config
        self.ollama_model = os.environ.get("ELI_OLLAMA_MODEL") or eli_config.chat_model()
        print(f"Fast chat model initialized: {self.model_type}")
    
    def detect_model(self):
        """Detect available chat models."""
        # Check for Ollama
        try:
            import ollama
            # Quick test
            try:
                ollama.list()
                return "ollama"
            except:
                return "simple"
        except ImportError:
            return "simple"
    
    def respond(self, prompt, context=None, timeout=None):
    
        """Generate a response with env-configurable timeout (no 3/5s clamps)."""
    
        if timeout is None:
    
            timeout = _env_timeout(120)
    
        else:
    
            try:
    
                timeout = int(timeout)
    
            except Exception:
    
                timeout = _env_timeout(120)
    
    
    
        if self.model_type == "ollama":
    
            return self.fast_ollama_response(prompt, timeout)
    
        else:
    
            return self.fast_simple_response(prompt)

    def fast_ollama_response(self, prompt, timeout=10):
        """Fast Ollama response with strict timeout."""
        try:
            import ollama
            
            # Prepare simple message
            messages = [{"role": "user", "content": prompt}]
            
            # Use queue for thread communication
            result_queue = queue.Queue()
            
            def make_call():
                try:
                    response = ollama.chat(
                        model=self.ollama_model,
                        messages=messages,
                        options={
                            "temperature": 0.7,
                            "num_predict": min(512, max(150, int(timeout * 8)))  # Short responses for speed
                        }
                    )
                    result_queue.put(('success', response['message']['content']))
                except Exception as e:
                    result_queue.put(('error', str(e)))
            
            # Start thread
            thread = threading.Thread(target=make_call)
            thread.daemon = True
            thread.start()
            
            # Wait with timeout
            thread.join(timeout=timeout)
            
            if thread.is_alive():
                print(f"Ollama timeout after {timeout} seconds")
                return self.fast_simple_response(prompt) + f"\n\n[Note: Response took too long. Using faster reply.]"
            
            # Get result
            try:
                result_type, result = result_queue.get(timeout=2)
                if result_type == 'success':
                    return result
                else:
                    print(f"Ollama error: {result}")
                    return self.fast_simple_response(prompt)
            except queue.Empty:
                print("Ollama queue empty")
                return self.fast_simple_response(prompt)
                
        except Exception as e:
            print(f"Ollama setup error: {e}")
            return self.fast_simple_response(prompt)
    
    def fast_simple_response(self, prompt):
        """Fast intelligent response without external calls."""
        prompt_lower = prompt.lower()
        
        # Quick keyword matching for common topics
        if 'meaning of life' in prompt_lower:
            responses = [
                "The meaning of life is a deeply personal question. Many find meaning in connection, growth, creativity, or contribution.",
                "Life's meaning might be in the journey itself - in learning, loving, and experiencing the world.",
                "Philosophers have long debated life's meaning. Some say we create our own meaning through choices and values."
            ]
            return random.choice(responses)
        
        if any(word in prompt_lower for word in ['physics', 'quantum', 'qft', 'science']):
            responses = [
                "Physics explores the fundamental nature of reality. Quantum physics reveals a strange, probabilistic world at small scales.",
                "Science helps us understand the universe through observation and reason. It's an ongoing journey of discovery.",
                "The scientific method - observe, hypothesize, test, refine - has transformed our understanding of nature."
            ]
            return random.choice(responses)
        
        if any(word in prompt_lower for word in ['consciousness', 'mind', 'awareness']):
            responses = [
                "Consciousness remains one of science's great mysteries - how subjective experience emerges from physical processes.",
                "The nature of mind and awareness fascinates philosophers, scientists, and spiritual thinkers alike.",
                "Consciousness involves awareness, perception, and subjective experience - topics at the frontier of neuroscience."
            ]
            return random.choice(responses)
        
        # Generic fast responses
        responses = [
            f"That's an interesting thought about '{prompt}'. I'm here to help with both conversation and practical tasks!",
            f"Thanks for sharing that. Regarding '{prompt}', I'm designed to assist with various kinds of questions and tasks.",
            f"I appreciate the conversation about '{prompt}'. Feel free to ask me anything or request specific assistance!"
        ]
        return random.choice(responses)

# Global instance
_fast_chat_model_instance = None

def get_fast_chat_model():
    """Get singleton fast chat model instance."""
    global _fast_chat_model_instance
    if _fast_chat_model_instance is None:
        _fast_chat_model_instance = FastChatModel()
    return _fast_chat_model_instance

def fast_chat_response(prompt, max_tokens=150):
    """Generate fast chat response."""
    return get_fast_chat_model().respond(prompt, timeout=8)  # 8 second timeout

# Backwards-compatible alias (older code expects ChatModelFast)
ChatModelFast = FastChatModel
