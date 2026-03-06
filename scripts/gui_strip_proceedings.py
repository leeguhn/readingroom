#!/usr/bin/env python3
"""
Simple Tkinter GUI to select top-level JSON keys to remove from conference proceeding files.

Usage: run the script, click "Open JSON", check keys you want to remove, set output filename, then click "Save Stripped JSON".
"""
import json
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Tuple, Optional


class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, height=300)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        # update scrollregion when the inner frame changes size
        self.scrollable_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        # create window for the inner frame
        self._inner_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Keep inner frame as wide as the canvas so checkboxes don't get clipped
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Bind mousewheel only while the pointer is over the canvas area
        self.canvas.bind("<Enter>", lambda e: self._bind_mousewheel())
        self.canvas.bind("<Leave>", lambda e: self._unbind_mousewheel())
        self.scrollable_frame.bind("<Enter>", lambda e: self._bind_mousewheel())
        self.scrollable_frame.bind("<Leave>", lambda e: self._unbind_mousewheel())

    def _on_canvas_configure(self, event):
        # Stretch the inner frame to match canvas width
        self.canvas.itemconfig(self._inner_id, width=event.width)

    def _on_mousewheel(self, event):
        # Windows / Mac: event.delta; Linux: Button-4 / Button-5 handled via event.num
        if hasattr(event, 'delta') and event.delta:
            delta = int(-1 * (event.delta / 120))
            if delta == 0:
                delta = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(delta, "units")
        else:
            if event.num == 5:
                self.canvas.yview_scroll(1, "units")
            elif event.num == 4:
                self.canvas.yview_scroll(-1, "units")

    def _bind_mousewheel(self):
        try:
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.canvas.bind_all("<Button-4>", self._on_mousewheel)
            self.canvas.bind_all("<Button-5>", self._on_mousewheel)
        except Exception:
            pass

    def _unbind_mousewheel(self):
        try:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")
        except Exception:
            pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Strip Proceedings — GUI")
        self.geometry("720x520")

        self.file_path: Optional[Path] = None
        self.json_data: Optional[Dict[str, Any]] = None
        self.vars: Dict[str, tk.BooleanVar] = {}
        self.path_map: Dict[str, Tuple[str, ...]] = {}
        self.output_var = tk.StringVar()
        self.file_list: List[Path] = []

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)

        open_ref = ttk.Button(top, text="Open Reference JSON", command=self.open_reference_file)
        open_ref.pack(side="left")

        open_many = ttk.Button(top, text="Open JSONs...", command=self.open_files)
        open_many.pack(side="left", padx=(6,0))

        self.file_label = ttk.Label(top, text="No files loaded", width=80)
        self.file_label.pack(side="left", padx=8)

        mid = ttk.LabelFrame(self, text="Top-level keys from reference (check to KEEP)")
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        self.scroll = ScrollableFrame(mid)
        self.scroll.pack(fill="both", expand=True)

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=8, pady=8)

        # Overwrite inputs directly. Optionally create backups before writing.
        self.backup_var = tk.BooleanVar(value=True)
        backup_cb = ttk.Checkbutton(controls, text="Copy original JSON to 'backups' folder before overwrite", variable=self.backup_var)
        backup_cb.grid(row=0, column=1, padx=8, sticky="w")

        select_all = ttk.Button(controls, text="Select All", command=self.select_all)
        select_all.grid(row=1, column=0, pady=6, sticky="w")

        deselect_all = ttk.Button(controls, text="Deselect All", command=self.deselect_all)
        deselect_all.grid(row=1, column=1, pady=6, sticky="w")

        preview_btn = ttk.Button(controls, text="Preview", command=self.preview)
        preview_btn.grid(row=1, column=2, pady=6, sticky="e")

        save_btn = ttk.Button(self, text="Save Stripped JSON", command=self.save)
        save_btn.pack(side="right", padx=8, pady=6)

        note = ttk.Label(self, text="Note: the reference JSON is the keep-template. Loaded files are truncated to only the checked categories and subcategories from that reference.")
        note.pack(side="left", padx=8)

    def open_file(self):
        # kept for backward compatibility
        self.open_reference_file()

    def open_reference_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json" )])
        if not path:
            return
        self.file_path = Path(path)
        self.file_label.config(text=f"Reference: {self.file_path.name}")
        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                self.json_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load JSON: {e}")
            return

        if not isinstance(self.json_data, dict):
            messagebox.showerror("Unsupported", "Top-level JSON is not an object (expected dict)")
            self.json_data = None
            return

        self.populate_checklist()
        default_out = self.file_path.with_name(self.file_path.stem + ".stripped" + self.file_path.suffix)
        self.output_var.set(str(default_out))

    def open_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("JSON files", "*.json" )])
        if not paths:
            return
        self.file_list = [Path(p) for p in paths]
        self.file_label.config(text=f"Loaded {len(self.file_list)} file(s); reference: {self.file_path.name if self.file_path else 'none'}")
        # if no reference selected yet, use the first file as reference
        if not self.json_data:
            try:
                with self.file_list[0].open("r", encoding="utf-8") as f:
                    self.json_data = json.load(f)
                if isinstance(self.json_data, dict):
                    self.populate_checklist()
                else:
                    messagebox.showerror("Unsupported", "Reference top-level JSON is not an object (expected dict)")
                    self.json_data = None
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load reference from first file: {e}")

    def populate_checklist(self):
        # clear existing
        for child in self.scroll.scrollable_frame.winfo_children():
            child.destroy()
        self.vars.clear()
        self.path_map.clear()

        paths = []
        def gather(d: Any, prefix: Tuple[str, ...] = ()):  # depth-first
            if isinstance(d, dict):
                for k in sorted(d.keys()):
                    p = prefix + (k,)
                    paths.append(p)
                    gather(d[k], p)
            elif isinstance(d, list):
                # inspect first element if it's a dict to surface nested keys
                if len(d) > 0 and isinstance(d[0], dict):
                    # show same prefix (list container) and then its inner keys
                    if prefix:
                        # don't add extra entry for list indices
                        for k in sorted(d[0].keys()):
                            p = prefix + (k,)
                            paths.append(p)
                            gather(d[0][k], p)

        gather(self.json_data, ())

        # create checkbuttons with indentation based on depth and attach toggle handler
        for i, p in enumerate(paths):
            depth = len(p) - 1
            label = p[-1]
            var = tk.BooleanVar(value=True)
            keystr = "|".join(p)
            cb = ttk.Checkbutton(self.scroll.scrollable_frame, text=label, variable=var, command=lambda ks=keystr: self.on_toggle(ks))
            cb.grid(row=i, column=0, sticky="w", padx=(8 + depth * 16), pady=2)
            # ensure scrolling stays active when hovering over the checkbox itself
            # Re-activate scrolling when pointer enters a checkbox inside the list
            try:
                cb.bind("<Enter>", lambda e, s=self.scroll: s._bind_mousewheel())
                cb.bind("<Leave>", lambda e, s=self.scroll: s._bind_mousewheel())
            except Exception:
                pass
            self.vars[keystr] = var
            self.path_map[keystr] = p

        # build children index for quick descendant lookups
        self.children_index = {k: [] for k in self.path_map}
        for k, p in self.path_map.items():
            for k2, p2 in self.path_map.items():
                if k2 != k and len(p2) > len(p) and p2[: len(p)] == p:
                    self.children_index[k].append(k2)

    def browse_output(self):
        # kept for compatibility but output filename is ignored when overwriting inputs
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if p:
            messagebox.showinfo("Info", "Selected output filename will be ignored; the program now overwrites input files directly.")

    def select_all(self):
        for v in self.vars.values():
            v.set(True)

    def deselect_all(self):
        for v in self.vars.values():
            v.set(False)

    def on_toggle(self, keystr: str):
        """When a checkbox is toggled, propagate the same state to all descendant paths."""
        if keystr not in self.vars:
            return
        val = self.vars[keystr].get()
        # Try to minimize layout churn: temporarily disable geometry propagation
        try:
            frame = self.scroll.scrollable_frame
            # disable geometry propagation so many .set() calls don't cause repeated reflow
            frame.grid_propagate(False)
        except Exception:
            frame = None

        try:
            for child in getattr(self, 'children_index', {}).get(keystr, []):
                if child in self.vars:
                    self.vars[child].set(val)
        finally:
            # re-enable geometry propagation and flush pending updates
            try:
                if frame is not None:
                    frame.grid_propagate(True)
            except Exception:
                pass
            try:
                self.update_idletasks()
            except Exception:
                pass

    def preview(self):
        if not self.json_data:
            messagebox.showinfo("No file", "No JSON file loaded")
            return
        to_keep = [k for k, v in self.vars.items() if v.get()]
        to_remove_explicit = [k for k, v in self.vars.items() if not v.get()]
        nice_keep = ["/".join(self.path_map[k]) for k in to_keep]
        nice_remove = ["/".join(self.path_map[k]) for k in to_remove_explicit]
        msg = f"Will KEEP {len(to_keep)} reference path(s):\n{nice_keep}"
        if nice_remove:
            msg += f"\n\nExplicitly EXCLUDED from the reference template:\n{nice_remove}"
        msg += "\n\nEach loaded JSON will be truncated to only the categories and subcategories present in the resulting reference template."
        messagebox.showinfo("Preview", msg)

    def save(self):
        if not self.json_data:
            messagebox.showerror("No file", "No JSON file loaded")
            return
        out_path = self.output_var.get().strip()
        if not out_path:
            messagebox.showerror("Output", "Please set an output filename")
            return
        out = Path(out_path)
        explicitly_unchecked = [k for k, v in self.vars.items() if not v.get()]
        if not self.path_map:
            if not messagebox.askyesno("Confirm", "No reference keys found. Overwrite files anyway?"):
                return

        def remove_path(obj: Any, path: Tuple[str, ...]):
            if not path:
                return
            key = path[0]
            rest = path[1:]
            if isinstance(obj, dict):
                if key in obj:
                    if rest:
                        val = obj.get(key)
                        if isinstance(val, dict):
                            remove_path(val, rest)
                        elif isinstance(val, list):
                            for item in val:
                                if isinstance(item, dict):
                                    remove_path(item, rest)
                    else:
                        obj.pop(key, None)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        remove_path(item, path)

        def prune_to_reference(data: Any, reference: Any) -> Any:
            if isinstance(reference, dict):
                if not isinstance(data, dict):
                    return data
                pruned_dict = {}
                for key, ref_value in reference.items():
                    if key in data:
                        pruned_dict[key] = prune_to_reference(data[key], ref_value)
                return pruned_dict

            if isinstance(reference, list):
                if not isinstance(data, list):
                    return data
                if not reference:
                    return data
                template = reference[0]
                if isinstance(template, (dict, list)):
                    return [prune_to_reference(item, template) for item in data]
                return data

            return data

        # determine targets
        targets: List[Path] = []
        if hasattr(self, 'file_list') and len(self.file_list) > 0:
            targets = self.file_list
        elif self.file_path:
            targets = [self.file_path]
        else:
            messagebox.showerror("No files", "No input files loaded")
            return

        if not messagebox.askyesno("Confirm overwrite", f"This will overwrite {len(targets)} file(s). Continue?"):
            return

        reference_template = json.loads(json.dumps(self.json_data))
        for keystr in explicitly_unchecked:
            path = self.path_map.get(keystr)
            if path:
                remove_path(reference_template, path)

        # apply removals and overwrite each file (with optional backup)
        failed = []
        for infile in targets:
            try:
                with infile.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                failed.append(str(infile))
                continue

            pruned = prune_to_reference(data, reference_template)

            if self.backup_var.get():
                bak_dir = infile.parent / "backups"
                try:
                    bak_dir.mkdir(exist_ok=True)
                except Exception:
                    bak_dir = infile.parent  # fallback to same dir if mkdir fails
                bak = bak_dir / infile.name
                try:
                    shutil.copy2(infile, bak)
                except Exception:
                    # non-fatal, continue
                    pass

            try:
                with infile.open("w", encoding="utf-8") as f:
                    json.dump(pruned, f, ensure_ascii=False, indent=2)
            except Exception:
                failed.append(str(infile))

        if failed:
            messagebox.showwarning("Completed with errors", f"Some files failed: {failed}")
        else:
            messagebox.showinfo("Saved", f"Overwrote {len(targets)} file(s) successfully")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
