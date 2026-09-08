import tkinter as tk
import subprocess
import sys
import os
import tempfile
import threading
import pstats
import io
import shlex
import shutil

from tkinter import ttk, scrolledtext, filedialog

WINDOW_TITLE = "Python Profiler"
WINDOW_SIZE = "750x700"
SORT_OPTIONS = ("cumtime", "time", "calls", "name", "nfl")
DEFAULT_SORT = "cumtime"
DEFAULT_LIMIT = 20
LIMIT_MIN = 5
LIMIT_MAX = 100
OUTPUT_HEIGHT = 15
PROGRESS_BAR_LENGTH = 400


def get_python_executable():
    if getattr(sys, "frozen", False):
        python_exe = shutil.which("python") or shutil.which("python3")
        if not python_exe:
            raise RuntimeError("Python interpreter not found in PATH")
        return python_exe
    return sys.executable
    

class ProfilerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)

        self.process = None
        self.temp_file = None
        self.running = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Script path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.script_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.script_var, width=50).grid(row=0, column=1, padx=5)
        ttk.Button(main, text="Browse", command=self.browse_script).grid(row=0, column=2, padx=5)

        ttk.Label(main, text="Arguments:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.args_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.args_var, width=50).grid(row=1, column=1, padx=5)

        sort_frame = ttk.Frame(main)
        sort_frame.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=5)
        ttk.Label(sort_frame, text="Sort by:").pack(side=tk.LEFT, padx=(0, 5))
        self.sort_var = tk.StringVar(value=DEFAULT_SORT)
        sort_combo = ttk.Combobox(
            sort_frame,
            textvariable=self.sort_var,
            values=SORT_OPTIONS,
            state="readonly",
            width=10
        )
        sort_combo.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(sort_frame, text="Limit rows:").pack(side=tk.LEFT, padx=(0, 5))
        self.limit_var = tk.IntVar(value=DEFAULT_LIMIT)
        ttk.Spinbox(
            sort_frame,
            from_=LIMIT_MIN,
            to=LIMIT_MAX,
            textvariable=self.limit_var,
            width=5
        ).pack(side=tk.LEFT)

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=3, column=0, columnspan=3, pady=10)
        self.run_btn = ttk.Button(btn_frame, text="Run", command=self.run_profiling)
        self.run_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(
            btn_frame,
            text="Stop",
            command=self.stop_profiling,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        self.copy_btn = ttk.Button(btn_frame, text="Copy result", command=self.copy_result)
        self.copy_btn.pack(side=tk.LEFT, padx=5)
        self.clear_btn = ttk.Button(btn_frame, text="Clear output", command=self.clear_output)
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        self.progress = ttk.Progressbar(main, mode="indeterminate", length=PROGRESS_BAR_LENGTH)
        self.progress.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=5)
        self.progress.grid_remove()

        pane = ttk.PanedWindow(main, orient=tk.VERTICAL)
        pane.grid(row=5, column=0, columnspan=3, sticky=tk.NSEW, pady=5)

        top_frame = ttk.Frame(pane)
        self.output_text = scrolledtext.ScrolledText(top_frame, wrap=tk.WORD, height=OUTPUT_HEIGHT)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        pane.add(top_frame, weight=1)

        bottom_frame = ttk.Frame(pane)
        self.stats_text = scrolledtext.ScrolledText(bottom_frame, wrap=tk.WORD, height=OUTPUT_HEIGHT)
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        pane.add(bottom_frame, weight=1)

        main.columnconfigure(1, weight=1)
        main.rowconfigure(5, weight=1)
        

    def browse_script(self):
        filename = filedialog.askopenfilename(filetypes=[("Python files", "*.py")])
        if filename:
            self.script_var.set(filename)
            

    def run_profiling(self):
        script_path = self.script_var.get().strip()
        if not script_path:
            self.output_text.insert(tk.END, "Error: please specify a script path.\n")
            return
        if not os.path.isfile(script_path):
            self.output_text.insert(tk.END, f"Error: file not found: {script_path}\n")
            return

        self.clear_output()
        self.output_text.insert(tk.END, "Starting profiling...\n")
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.running = True

        self.progress.grid()
        self.progress.start(10)

        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pstats")
        self.temp_file.close()

        args_str = self.args_var.get().strip()
        script_args = shlex.split(args_str) if args_str else []

        try:
            python_exe = get_python_executable()
        except RuntimeError as e:
            self.output_text.insert(tk.END, f"Error: {e}\n")
            self.run_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.progress.stop()
            self.progress.grid_remove()
            return

        cmd = [python_exe, "-m", "cProfile", "-o", self.temp_file.name, script_path] + script_args

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._monitor_process, daemon=True).start()
        

    def _read_output(self):
        for line in iter(self.process.stdout.readline, ""):
            if not line:
                break
            self.root.after(0, lambda l=line: self.output_text.insert(tk.END, l))
        self.process.stdout.close()
        

    def _monitor_process(self):
        self.process.wait()
        self.running = False
        self.root.after(0, self._on_process_done)
        

    def _on_process_done(self):
        self.run_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.progress.stop()
        self.progress.grid_remove()

        if self.temp_file and os.path.exists(self.temp_file.name):
            try:
                sort_key = self.sort_var.get()
                limit = self.limit_var.get()
                stats = pstats.Stats(self.temp_file.name)
                stats.sort_stats(sort_key)
                stream = io.StringIO()
                stats.stream = stream
                stats.print_stats(limit)
                result = stream.getvalue()
                stream.close()

                self.stats_text.insert(tk.END, "--- Profiling statistics ---\n")
                self.stats_text.insert(tk.END, result)
            except Exception as e:
                self.stats_text.insert(tk.END, f"Error reading statistics: {e}\n")
            finally:
                os.unlink(self.temp_file.name)
                self.temp_file = None
        else:
            self.stats_text.insert(tk.END, "Statistics file not found.\n")

        self.process = None
        

    def stop_profiling(self):
        if self.process and self.process.poll() is None:
            self.output_text.insert(tk.END, "\nStopping by user request...\n")
            self.stop_btn.config(state=tk.DISABLED)
            self.progress.stop()
            self.progress.grid_remove()
            try:
                self.process.terminate()

                def force_kill():
                    if self.process and self.process.poll() is None:
                        self.process.kill()
                        self.output_text.insert(tk.END, "Process forcefully terminated.\n")

                self.root.after(2000, force_kill)
            except Exception as e:
                self.output_text.insert(tk.END, f"Error while stopping: {e}\n")

    
    def copy_result(self):
        text = self.output_text.get(1.0, tk.END).strip()
        stats = self.stats_text.get(1.0, tk.END).strip()
        full_text = text + "\n\n" + stats if stats else text
        if full_text.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(full_text)
            self.output_text.insert(tk.END, "\n[Result copied to clipboard]\n")
        else:
            self.output_text.insert(tk.END, "\n[No data to copy]\n")
            

    def clear_output(self):
        self.output_text.delete(1.0, tk.END)
        self.stats_text.delete(1.0, tk.END)
        

    def on_close(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ProfilerApp(root)
    root.mainloop()
