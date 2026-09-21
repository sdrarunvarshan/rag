"""
Start Arize Phoenix server for trace collection and observability UI.
Run this before starting the RAG API to enable tracing.
"""

import subprocess
import sys
from pathlib import Path

def start_phoenix():
    """Start Phoenix server on default port 6006."""
    print("Starting Phoenix server...")
    print("Phoenix UI will be available at http://localhost:6006")
    print("Press Ctrl+C to stop the server")
    
    try:
        # Start Phoenix using CLI
        subprocess.run(
            ["phoenix", "serve"],
            check=True,
        )
    except KeyboardInterrupt:
        print("\nPhoenix server stopped")
    except Exception as e:
        print(f"Error starting Phoenix: {e}")
        sys.exit(1)

if __name__ == "__main__":
    start_phoenix()
