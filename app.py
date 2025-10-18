import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

def shorten(path, max_len=68):
    """Return a shortened path like /very/…/deep/file.pdf for display only."""
    if len(path) <= max_len:
        return path
    head, tail = os.path.split(path)
    head2 = head[: max_len // 2 - 2]
    tail2 = tail[-(max_len - len(head2) - 5):]
    return f"{head2}…/{tail2}"

class PDFSplitterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Splitter")
        self.geometry("640x260")
        self.resizable(False, False)

        # state
        self.input_path = None
        self.output_dir = None

        # UI
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 12, "pady": 8}

        # Input file picker (button + read-only label)
        frm_in = ttk.Frame(self)
        frm_in.pack(fill="x", **pad)
        ttk.Label(frm_in, text="PDF file:").pack(side="left")
        ttk.Button(frm_in, text="Select PDF…", command=self.pick_file).pack(side="left", padx=8)
        self.lbl_in = ttk.Label(frm_in, text="(none selected)", foreground="#555")
        self.lbl_in.pack(side="left", padx=8)

        # Output folder picker (button + read-only label)
        frm_out = ttk.Frame(self)
        frm_out.pack(fill="x", **pad)
        ttk.Label(frm_out, text="Output folder:").pack(side="left")
        ttk.Button(frm_out, text="Select folder…", command=self.pick_output_dir).pack(side="left", padx=8)
        self.lbl_out = ttk.Label(frm_out, text="(will default next to the PDF)", foreground="#555")
        self.lbl_out.pack(side="left", padx=8)

        # Pages per file (numeric updown)
        frm_pages = ttk.Frame(self)
        frm_pages.pack(fill="x", **pad)
        ttk.Label(frm_pages, text="Pages per file:").pack(side="left")
        self.pages_var = tk.StringVar(value="10")
        self.spn_pages = ttk.Spinbox(frm_pages, from_=1, to=9999, width=8, textvariable=self.pages_var, justify="right")
        self.spn_pages.pack(side="left", padx=8)

        # Progress
        frm_prog = ttk.Frame(self)
        frm_prog.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(frm_prog, mode="determinate")
        self.progress.pack(fill="x", expand=True)

        # Buttons row + status
        frm_btn = ttk.Frame(self)
        frm_btn.pack(fill="x", **pad)
        self.btn_split = ttk.Button(frm_btn, text="Split PDF", command=self.start_split)
        self.btn_split.pack(side="left")
        ttk.Button(frm_btn, text="Exit", command=self.destroy).pack(side="right")

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=4)

    def pick_file(self):
        path = filedialog.askopenfilename(title="Select PDF", filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        self.input_path = path
        # Suggest default output folder next to file
        base = os.path.splitext(os.path.basename(path))[0]
        default_dir = os.path.join(os.path.dirname(path), f"{base}_split")
        if not self.output_dir:
            self.output_dir = default_dir
            self.lbl_out.config(text=shorten(self.output_dir))
        self.lbl_in.config(text=shorten(self.input_path), foreground="black")

    def pick_output_dir(self):
        path = filedialog.askdirectory(title="Select output folder")
        if not path:
            return
        self.output_dir = path
        self.lbl_out.config(text=shorten(self.output_dir), foreground="black")

    def start_split(self):
        if not self.input_path:
            messagebox.showwarning("Missing file", "Please select a PDF file.")
            return
        # Validate pages per file
        pages_str = self.pages_var.get().strip()
        if not pages_str.isdigit() or int(pages_str) <= 0:
            messagebox.showwarning("Invalid pages", "Pages per file must be a positive integer.")
            return
        ppf = int(pages_str)

        # Ensure output directory
        out_dir = self.output_dir
        if not out_dir:
            base = os.path.splitext(os.path.basename(self.input_path))[0]
            out_dir = os.path.join(os.path.dirname(self.input_path), f"{base}_split")
            self.output_dir = out_dir
            self.lbl_out.config(text=shorten(out_dir))
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Folder error", f"Cannot create output folder:\n{e}")
            return

        # lock UI
        self.btn_split.config(state="disabled")
        self.status.set("Starting split…")
        self.progress.config(value=0, maximum=100)

        threading.Thread(
            target=self._split_worker, args=(self.input_path, out_dir, ppf), daemon=True
        ).start()

    def _split_worker(self, in_path, out_dir, ppf):
        try:
            # open reader (handle encryption)
            try:
                reader = PdfReader(in_path)
            except PdfReadError as e:
                self._set_status(f"Encrypted or unreadable PDF: {e}")
                # Try password prompt
                try:
                    reader = PdfReader(in_path)
                    if reader.is_encrypted:
                        pwd = simpledialog.askstring("Password", "Enter PDF password:", show="*")
                        if not pwd:
                            self._set_done("Cancelled (no password).")
                            return
                        ok = reader.decrypt(pwd)
                        if not ok:
                            self._set_done("Wrong password.")
                            return
                except Exception as e2:
                    self._set_done(f"Failed to open PDF: {e2}")
                    return

            if getattr(reader, "is_encrypted", False):
                try:
                    if not reader.decrypt(""):
                        pwd = simpledialog.askstring("Password", "Enter PDF password:", show="*")
                        if not pwd or not reader.decrypt(pwd):
                            self._set_done("Could not decrypt PDF.")
                            return
                except Exception:
                    pass

            total_pages = len(reader.pages)
            if total_pages == 0:
                self._set_done("PDF has no pages.")
                return

            total_parts = (total_pages + ppf - 1) // ppf
            self._set_progress(0, total_parts)

            base = os.path.splitext(os.path.basename(in_path))[0]
            for part_idx, start in enumerate(range(0, total_pages, ppf), start=1):
                end = min(start + ppf, total_pages)
                writer = PdfWriter()
                for p in range(start, end):
                    writer.add_page(reader.pages[p])

                out_name = f"{base}_part{part_idx:03d}.pdf"
                out_path = os.path.join(out_dir, out_name)
                with open(out_path, "wb") as f:
                    writer.write(f)

                self._set_status(f"Wrote {out_name} ({start+1}-{end} of {total_pages})")
                self._set_progress(part_idx, total_parts)

            self._set_done(f"Done. Created {total_parts} file(s) in:\n{out_dir}")

        except Exception as e:
            self._set_done(f"Error: {e}")
        finally:
            self.after(0, lambda: self.btn_split.config(state="normal"))

    # UI helpers (main-thread safe)
    def _set_status(self, text):
        self.after(0, lambda: self.status.set(text))

    def _set_progress(self, part_idx, total_parts):
        def _u():
            self.progress.config(maximum=total_parts, value=part_idx)
        self.after(0, _u)

    def _set_done(self, text):
        self.after(0, lambda: (self.status.set(text), self.progress.stop()))

if __name__ == "__main__":
    # macOS/HiDPI nicety (safe on Windows/Linux too)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = PDFSplitterApp()
    app.mainloop()
