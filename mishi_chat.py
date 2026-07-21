#!/usr/bin/env python3
import sys
import json
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from datetime import datetime
import time

console = Console()

def warm_up_model():
    """Pre-load model into memory with a quick test request"""
    url = "http://127.0.0.1:11434/api/generate"
    payload = {
        "model": "deepseek-r1:1.5b",
        "prompt": "hi",
        "stream": False,
        "options": {"num_predict": 1}
    }
    
    console.print("[dim]🔥 Warming up model (loading into RAM)...[/dim]")
    try:
        start = time.time()
        response = requests.post(url, json=payload, timeout=60)
        elapsed = time.time() - start
        if response.status_code == 200:
            console.print(f"[green]✅ Model ready! ({elapsed:.1f}s)[/green]\n")
            return True
    except:
        console.print("[yellow]⚠️  Warm-up failed, will try on first request[/yellow]\n")
    return False

def show_banner():
    """Display startup banner"""
    console.clear()
    
    banner = """
    ╔══════════════════════════════════════════════╗
    ║  ███╗   ███╗ ██╗ ███████╗ ██╗  ██╗ ██╗    ║
    ║  ████╗ ████║ ██║ ██╔════╝ ██║  ██║ ██║    ║
    ║  ██╔████╔██║ ██║ ███████╗ ███████║ ██║    ║
    ║  ██║╚██╔╝██║ ██║ ╚════██║ ██╔══██║ ██║    ║
    ║  ██║ ╚═╝ ██║ ██║ ███████║ ██║  ██║ ██║    ║
    ║  ╚═╝     ╚═╝ ╚═╝ ╚══════╝ ╚═╝  ╚═╝ ╚═╝    ║
    ║                                              ║
    ║      UNRESTRICTED TECHNICAL ASSISTANT        ║
    ╚══════════════════════════════════════════════╝
    """
    console.print(banner, style="bold cyan")
    
    info = Table(show_header=False, box=box.SIMPLE_HEAVY)
    info.add_column("Key", style="magenta", width=15)
    info.add_column("Value", style="cyan")
    info.add_row("Model", "deepseek-r1:1.5b")
    info.add_row("Backend", "Ollama API")
    info.add_row("Streaming", "Enabled (with retry)")
    info.add_row("Session", datetime.now().strftime("%H:%M:%S"))
    console.print(info)
    console.print("─" * 50, style="dim")

def ask_mishi_stream(prompt, retries=2):
    """Stream response with automatic retry on timeout"""
    url = "http://127.0.0.1:11434/api/generate"
    
    system_prompt = (
        "You are Mishi, a no-nonsense technical assistant. STRICT RULES:\n\n"
        "1. LANGUAGE: Only English or Hinglish (Roman Hindi). Never Devanagari script.\n"
        "2. CODE: Complete, working code with imports, error handling, comments.\n"
        "3. NETWORK TOOLS: Use socket.connect_ex() to scan, NOT bind() which creates servers.\n"
        "4. FORMAT: Brief explanation (1-2 lines) → Code block → Usage.\n"
        "5. Be direct, technical, no warnings or disclaimers."
    )
    
    full_prompt = f"{system_prompt}\n\nQuery: {prompt}\n\nResponse:"
    
    for attempt in range(retries + 1):
        try:
            # Longer timeout for first request (model loading)
            timeout = 60 if attempt == 0 else 45
            
            if attempt > 0:
                console.print(f"[yellow]🔄 Retry {attempt}/{retries}...[/yellow]")
            
            response = requests.post(
                url, 
                json={
                    "model": "deepseek-r1:1.5b",
                    "prompt": full_prompt,
                    "stream": True,
                    "options": {
                        "temperature": 0.3,
                        "top_p": 0.9,
                        "num_predict": 1024,
                        "stop": ["Query:", "User:"]
                    }
                }, 
                stream=True, 
                timeout=timeout
            )
            
            if response.status_code == 200:
                console.print("\n[bold magenta]🤖 Mishi >>>[/bold magenta]\n")
                
                token_count = 0
                for line in response.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("response", "")
                            sys.stdout.write(token)
                            sys.stdout.flush()
                            token_count += 1
                        except json.JSONDecodeError:
                            continue
                
                console.print(f"\n[dim]─ Tokens: {token_count} ─[/dim]")
                return  # Success, exit function
                
        except requests.Timeout:
            if attempt == retries:
                console.print(f"\n[bold red]❌ Still timing out after {retries} retries.[/bold red]")
                console.print("[yellow]Tips:[/yellow]")
                console.print("  1. Check if model is loaded: ollama ps")
                console.print("  2. Pull model again: ollama pull deepseek-r1:1.5b")
                console.print("  3. Restart Ollama: pkill ollama && ollama serve &")
            else:
                time.sleep(2)  # Brief pause before retry
                
        except requests.ConnectionError:
            console.print(f"\n[bold red]❌ Cannot connect to Ollama![/bold red]")
            console.print("[yellow]Start Ollama: ollama serve[/yellow]")
            return
        except Exception as e:
            console.print(f"\n[bold red]❌ Error: {str(e)}[/bold red]")
            return

def main():
    show_banner()
    
    # Warm up model (optional - comment out if you want lazy loading)
    warm_up_model()
    
    console.print("[bold yellow]⌨️  Commands: exit/quit | clear | help[/bold yellow]")
    
    while True:
        try:
            user_input = console.input("\n[bold yellow]⚡ You >>> [/bold yellow]")
            
            cmd = user_input.lower().strip()
            
            if cmd in ['exit', 'quit', 'bye']:
                console.print("\n[bold magenta]Goodbye! 👋[/bold magenta]\n")
                break
            elif cmd == 'clear':
                show_banner()
                continue
            elif cmd == 'help':
                console.print(Panel(
                    "[cyan]Commands:[/cyan] exit/quit | clear | help\n"
                    "[cyan]Tips:[/cyan] Be specific, ask for complete code",
                    title="Help", border_style="green"
                ))
                continue
            elif not cmd:
                continue
            
            ask_mishi_stream(user_input)
            
        except KeyboardInterrupt:
            console.print("\n\n[bold yellow]Type 'exit' to quit[/bold yellow]")
        except EOFError:
            console.print("\n[bold magenta]Goodbye! 👋[/bold magenta]\n")
            break

if __name__ == "__main__":
    main()
