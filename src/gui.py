"""Tkinter GUI: transcription tab + dictionary editor tab.

Transcription runs on a worker thread; UI updates are marshalled back to the
Tk main thread through a queue polled with ``after()`` (Tk is not thread-safe).
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import paths
from dictionary import ReplacementRule, UserDictionary, WordEntry

AUDIO_FILETYPES = [
    ("音訊/影片檔", "*.m4a *.mp3 *.wav *.aac *.flac *.ogg *.wma *.mp4 *.mov *.webm"),
    ("所有檔案", "*.*"),
]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("離線中文錄音轉文字")
        self.geometry("860x640")
        self.minsize(720, 520)

        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._transcriber = None  # lazy-loaded on first run
        self._segments: list = []

        self.dictionary = UserDictionary.load(paths.dictionary_path())

        self._original_text: str = ""  # post-processed transcript before user edits

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_transcribe_tab(notebook)
        self._build_dictionary_tab(notebook)
        self._build_learn_tab(notebook)

        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Transcribe tab
    # ------------------------------------------------------------------

    def _build_transcribe_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  轉錄  ")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=10, pady=(10, 4))

        self.file_var = tk.StringVar()
        ttk.Label(top, text="音訊檔：").pack(side="left")
        ttk.Entry(top, textvariable=self.file_var).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        ttk.Button(top, text="選擇檔案…", command=self._choose_file).pack(side="left")

        ctrl = ttk.Frame(tab)
        ctrl.pack(fill="x", padx=10, pady=4)
        self.start_btn = ttk.Button(ctrl, text="開始轉錄", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(
            ctrl, text="取消", command=self._cancel_run, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="就緒")
        ttk.Label(ctrl, textvariable=self.status_var).pack(side="left", padx=12)

        self.progress = ttk.Progressbar(tab, maximum=1.0)
        self.progress.pack(fill="x", padx=10, pady=4)

        self.text = tk.Text(tab, wrap="char", font=("", 13))
        self.text.pack(fill="both", expand=True, padx=10, pady=4)
        scroll = ttk.Scrollbar(self.text, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        bottom = ttk.Frame(tab)
        bottom.pack(fill="x", padx=10, pady=(4, 10))
        self.save_txt_btn = ttk.Button(
            bottom, text="儲存純文字 (.txt)", command=self._save_txt, state="disabled"
        )
        self.save_txt_btn.pack(side="left")
        self.save_srt_btn = ttk.Button(
            bottom, text="儲存字幕 (.srt)", command=self._save_srt, state="disabled"
        )
        self.save_srt_btn.pack(side="left", padx=6)
        self.learn_btn = ttk.Button(
            bottom,
            text="從修正學習",
            command=self._learn_from_edits,
            state="disabled",
        )
        self.learn_btn.pack(side="left", padx=6)
        ttk.Label(
            bottom, text="（可直接在上方修改文字，再按「從修正學習」）", foreground="#777"
        ).pack(side="left")

    def _choose_file(self) -> None:
        filename = filedialog.askopenfilename(filetypes=AUDIO_FILETYPES)
        if filename:
            self.file_var.set(filename)

    def _start(self) -> None:
        audio = self.file_var.get().strip()
        if not audio:
            messagebox.showwarning("提示", "請先選擇音訊檔")
            return
        if not Path(audio).exists():
            messagebox.showerror("錯誤", f"找不到檔案：{audio}")
            return

        self._segments = []
        self._original_text = ""
        self._cancel.clear()
        self.text.delete("1.0", "end")
        self.progress["value"] = 0
        self.start_btn["state"] = "disabled"
        self.cancel_btn["state"] = "normal"
        self.save_txt_btn["state"] = "disabled"
        self.save_srt_btn["state"] = "disabled"
        self.learn_btn["state"] = "disabled"
        self.status_var.set("載入模型中…")

        self._worker = threading.Thread(
            target=self._run_transcription, args=(Path(audio),), daemon=True
        )
        self._worker.start()

    def _cancel_run(self) -> None:
        self._cancel.set()
        self.status_var.set("取消中…")

    def _run_transcription(self, audio_path: Path) -> None:
        """Worker thread: load model, transcribe, post-process each segment."""
        try:
            from postprocess import PostProcessor
            from transcriber import Transcriber

            if self._transcriber is None:
                self._transcriber = Transcriber(paths.model_dir())
            transcriber = self._transcriber

            # Dictionary snapshot for this run
            dictionary = UserDictionary.load(paths.dictionary_path())
            post = PostProcessor(dictionary)
            prompt = dictionary.build_initial_prompt(transcriber.count_tokens)

            self._queue.put(("status", "轉錄中…"))
            for seg in transcriber.transcribe(
                audio_path,
                initial_prompt=prompt,
                on_progress=lambda r: self._queue.put(("progress", r)),
                should_cancel=self._cancel.is_set,
            ):
                seg.text = post.process(seg.text)
                self._queue.put(("segment", seg))

            if self._cancel.is_set():
                self._queue.put(("status", "已取消"))
            else:
                self._queue.put(("progress", 1.0))
                self._queue.put(("status", "完成"))
        except Exception as exc:  # surface any failure to the user
            self._queue.put(("error", str(exc)))
        finally:
            self._queue.put(("done", None))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    self.progress["value"] = payload
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "segment":
                    self._segments.append(payload)
                    self.text.insert("end", payload.text + "\n")
                    self.text.see("end")
                elif kind == "error":
                    self.status_var.set("發生錯誤")
                    messagebox.showerror("錯誤", payload)
                elif kind == "done":
                    self.start_btn["state"] = "normal"
                    self.cancel_btn["state"] = "disabled"
                    if self._segments:
                        self.save_txt_btn["state"] = "normal"
                        self.save_srt_btn["state"] = "normal"
                        self.learn_btn["state"] = "normal"
                        # Snapshot for "learn from edits" comparison
                        self._original_text = self.text.get("1.0", "end-1c")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _default_save_name(self, ext: str) -> str:
        src = self.file_var.get().strip()
        return (Path(src).stem + ext) if src else ("transcript" + ext)

    def _save_txt(self) -> None:
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile=self._default_save_name(".txt")
        )
        if filename:
            Path(filename).write_text(
                "\n".join(s.text for s in self._segments) + "\n", encoding="utf-8"
            )
            self.status_var.set(f"已儲存：{filename}")

    def _save_srt(self) -> None:
        from transcriber import format_srt

        filename = filedialog.asksaveasfilename(
            defaultextension=".srt", initialfile=self._default_save_name(".srt")
        )
        if filename:
            Path(filename).write_text(format_srt(self._segments), encoding="utf-8")
            self.status_var.set(f"已儲存：{filename}")

    # ------------------------------------------------------------------
    # Learning (correction feedback)
    # ------------------------------------------------------------------

    def _learn_from_edits(self) -> None:
        """Compare the edited preview text with the original transcript."""
        current = self.text.get("1.0", "end-1c")
        if not self._original_text:
            return
        self._run_learning(self._original_text, current)

    def _build_learn_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  學習  ")

        hint = (
            "把校正後的文字「教」給程式：比對原始轉錄檔與你修改後的檔案，\n"
            "自動找出修正的地方並建議加入字典（同音字 → 詞彙表；其他 → 取代規則）。\n"
            "比對全程在本機進行，不使用網路。\n\n"
            "提示：儲存轉錄結果時請保留一份未修改的原始檔，校正時改另一份副本。"
        )
        ttk.Label(tab, text=hint, foreground="#555", justify="left").pack(
            anchor="w", padx=10, pady=(10, 8)
        )

        form = ttk.Frame(tab)
        form.pack(fill="x", padx=10)
        form.columnconfigure(1, weight=1)

        self.learn_orig_var = tk.StringVar()
        self.learn_fixed_var = tk.StringVar()
        for row, (label, var) in enumerate(
            [("原始轉錄檔：", self.learn_orig_var), ("校正後檔案：", self.learn_fixed_var)]
        ):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(form, textvariable=var).grid(
                row=row, column=1, sticky="ew", padx=6
            )
            ttk.Button(
                form,
                text="選擇檔案…",
                command=lambda v=var: self._pick_text_file(v),
            ).grid(row=row, column=2)

        ttk.Button(tab, text="開始比對", command=self._learn_from_files).pack(
            anchor="w", padx=10, pady=10
        )

    def _pick_text_file(self, var: tk.StringVar) -> None:
        filename = filedialog.askopenfilename(
            filetypes=[("文字檔", "*.txt"), ("所有檔案", "*.*")]
        )
        if filename:
            var.set(filename)

    @staticmethod
    def _read_text_file(path: Path) -> str:
        data = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "cp950"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def _learn_from_files(self) -> None:
        orig_path = self.learn_orig_var.get().strip()
        fixed_path = self.learn_fixed_var.get().strip()
        if not orig_path or not fixed_path:
            messagebox.showwarning("提示", "請選擇原始轉錄檔與校正後檔案")
            return
        for p in (orig_path, fixed_path):
            if not Path(p).exists():
                messagebox.showerror("錯誤", f"找不到檔案：{p}")
                return
        original = self._read_text_file(Path(orig_path))
        corrected = self._read_text_file(Path(fixed_path))
        self._run_learning(original, corrected)

    def _run_learning(self, original: str, corrected: str) -> None:
        from learn import apply_suggestions, extract_suggestions

        # Reload so we diff against the user's latest dictionary edits
        self.dictionary = UserDictionary.load(paths.dictionary_path())
        suggestions = extract_suggestions(original, corrected, self.dictionary)
        if not suggestions:
            messagebox.showinfo(
                "學習",
                "沒有找到可以學習的修正。\n"
                "（可能沒有差異、修改幅度太大，或字典已涵蓋這些修正）",
            )
            return
        accepted = SuggestionDialog(self, suggestions).result
        if not accepted:
            return
        apply_suggestions(accepted, self.dictionary)
        self._save_dictionary()
        messagebox.showinfo(
            "學習", f"已加入 {len(accepted)} 筆到字典，下次轉錄自動套用。"
        )

    # ------------------------------------------------------------------
    # Dictionary tab
    # ------------------------------------------------------------------

    def _build_dictionary_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  字典  ")

        hint = (
            "詞彙表：登錄正確的詞（如人名），轉錄結果中同音的字會自動改成這裡的寫法。\n"
            "取代規則：轉錄完成後，把「原文字」一律換成「替換為」，作為最終強制修正。"
        )
        ttk.Label(tab, text=hint, foreground="#555").pack(
            anchor="w", padx=10, pady=(10, 4)
        )

        panes = ttk.Frame(tab)
        panes.pack(fill="both", expand=True, padx=10, pady=4)
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(0, weight=1)

        # --- words table ---
        words_frame = ttk.LabelFrame(panes, text="詞彙表（同音字修正）")
        words_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.words_tree = ttk.Treeview(
            words_frame,
            columns=("word", "fuzzy", "prompt", "enabled"),
            show="headings",
            selectmode="browse",
        )
        for col, title, width in [
            ("word", "詞彙", 140),
            ("fuzzy", "模糊音", 60),
            ("prompt", "提示", 50),
            ("enabled", "啟用", 50),
        ]:
            self.words_tree.heading(col, text=title)
            self.words_tree.column(col, width=width, anchor="center")
        self.words_tree.column("word", anchor="w")
        self.words_tree.pack(fill="both", expand=True, padx=6, pady=6)

        wbtns = ttk.Frame(words_frame)
        wbtns.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(wbtns, text="新增", command=self._add_word).pack(side="left")
        ttk.Button(wbtns, text="編輯", command=self._edit_word).pack(side="left", padx=4)
        ttk.Button(wbtns, text="刪除", command=self._delete_word).pack(side="left")

        # --- replacement rules table ---
        rules_frame = ttk.LabelFrame(panes, text="取代規則（最後強制修正）")
        rules_frame.grid(row=0, column=1, sticky="nsew")

        self.rules_tree = ttk.Treeview(
            rules_frame,
            columns=("src", "dst", "enabled"),
            show="headings",
            selectmode="browse",
        )
        for col, title, width in [
            ("src", "原文字", 120),
            ("dst", "替換為", 120),
            ("enabled", "啟用", 50),
        ]:
            self.rules_tree.heading(col, text=title)
            self.rules_tree.column(col, width=width, anchor="center")
        self.rules_tree.column("src", anchor="w")
        self.rules_tree.column("dst", anchor="w")
        self.rules_tree.pack(fill="both", expand=True, padx=6, pady=6)

        rbtns = ttk.Frame(rules_frame)
        rbtns.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(rbtns, text="新增", command=self._add_rule).pack(side="left")
        ttk.Button(rbtns, text="編輯", command=self._edit_rule).pack(side="left", padx=4)
        ttk.Button(rbtns, text="刪除", command=self._delete_rule).pack(side="left")

        self._refresh_dictionary_views()

    def _refresh_dictionary_views(self) -> None:
        self.words_tree.delete(*self.words_tree.get_children())
        for i, w in enumerate(self.dictionary.words):
            self.words_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    w.word,
                    "是" if w.fuzzy else "否",
                    "是" if w.use_prompt else "否",
                    "是" if w.enabled else "否",
                ),
            )
        self.rules_tree.delete(*self.rules_tree.get_children())
        for i, r in enumerate(self.dictionary.replacements):
            self.rules_tree.insert(
                "", "end", iid=str(i), values=(r.src, r.dst, "是" if r.enabled else "否")
            )

    def _save_dictionary(self) -> None:
        self.dictionary.save(paths.dictionary_path())
        self._refresh_dictionary_views()

    # --- word dialogs ---

    def _add_word(self) -> None:
        result = WordDialog(self, title="新增詞彙").result
        if result:
            self.dictionary.words.append(result)
            self._save_dictionary()

    def _edit_word(self) -> None:
        sel = self.words_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        result = WordDialog(
            self, title="編輯詞彙", entry=self.dictionary.words[idx]
        ).result
        if result:
            self.dictionary.words[idx] = result
            self._save_dictionary()

    def _delete_word(self) -> None:
        sel = self.words_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        word = self.dictionary.words[idx].word
        if messagebox.askyesno("確認", f"刪除詞彙「{word}」？"):
            del self.dictionary.words[idx]
            self._save_dictionary()

    # --- rule dialogs ---

    def _add_rule(self) -> None:
        result = RuleDialog(self, title="新增取代規則").result
        if result:
            self.dictionary.replacements.append(result)
            self._save_dictionary()

    def _edit_rule(self) -> None:
        sel = self.rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        result = RuleDialog(
            self, title="編輯取代規則", rule=self.dictionary.replacements[idx]
        ).result
        if result:
            self.dictionary.replacements[idx] = result
            self._save_dictionary()

    def _delete_rule(self) -> None:
        sel = self.rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        rule = self.dictionary.replacements[idx]
        if messagebox.askyesno("確認", f"刪除規則「{rule.src} → {rule.dst}」？"):
            del self.dictionary.replacements[idx]
            self._save_dictionary()


class SuggestionDialog(tk.Toplevel):
    """Review dialog: tick the corrections to add to the dictionary."""

    def __init__(self, parent: tk.Tk, suggestions):
        super().__init__(parent)
        self.title("學習建議")
        self.geometry("560x360")
        self.result: list = []
        self._suggestions = suggestions
        self._checked = [s.preselected for s in suggestions]

        ttk.Label(
            self,
            text="找到以下修正，勾選要加入字典的項目（點一下列即可切換勾選）：",
        ).pack(anchor="w", padx=12, pady=(12, 6))

        self.tree = ttk.Treeview(
            self,
            columns=("pick", "kind", "src", "dst"),
            show="headings",
            selectmode="none",
        )
        for col, title, width, anchor in [
            ("pick", "加入", 50, "center"),
            ("kind", "類型", 170, "w"),
            ("src", "原本辨識", 130, "w"),
            ("dst", "修正為", 130, "w"),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=True, padx=12)

        for i, s in enumerate(suggestions):
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                values=("☑" if self._checked[i] else "☐", s.describe(), s.src, s.dst),
            )
        self.tree.bind("<Button-1>", self._toggle)

        btns = ttk.Frame(self)
        btns.pack(pady=10)
        ttk.Button(btns, text="加入勾選項目", command=self._ok).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left")

        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    def _toggle(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        i = int(row)
        self._checked[i] = not self._checked[i]
        s = self._suggestions[i]
        self.tree.item(
            row,
            values=("☑" if self._checked[i] else "☐", s.describe(), s.src, s.dst),
        )

    def _ok(self) -> None:
        self.result = [
            s for s, checked in zip(self._suggestions, self._checked) if checked
        ]
        self.destroy()


class WordDialog(tk.Toplevel):
    """Modal dialog for adding/editing a WordEntry."""

    def __init__(self, parent: tk.Tk, title: str, entry: WordEntry | None = None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result: WordEntry | None = None

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="詞彙（例：王小明）：").grid(row=0, column=0, sticky="w")
        self.word_var = tk.StringVar(value=entry.word if entry else "")
        word_entry = ttk.Entry(body, textvariable=self.word_var, width=24)
        word_entry.grid(row=0, column=1, pady=4)

        self.fuzzy_var = tk.BooleanVar(value=entry.fuzzy if entry else False)
        ttk.Checkbutton(
            body, text="模糊音比對（zh/z、l/n、in/ing 等視為同音）", variable=self.fuzzy_var
        ).grid(row=1, column=0, columnspan=2, sticky="w")

        self.prompt_var = tk.BooleanVar(value=entry.use_prompt if entry else True)
        ttk.Checkbutton(
            body, text="加入辨識提示（讓模型優先輸出此詞）", variable=self.prompt_var
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        self.enabled_var = tk.BooleanVar(value=entry.enabled if entry else True)
        ttk.Checkbutton(body, text="啟用", variable=self.enabled_var).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )

        btns = ttk.Frame(body)
        btns.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="確定", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left")

        word_entry.focus_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    def _ok(self) -> None:
        word = self.word_var.get().strip()
        if not word:
            messagebox.showwarning("提示", "請輸入詞彙", parent=self)
            return
        if len(word) < 2:
            messagebox.showwarning(
                "提示", "詞彙至少需要兩個字（單字容易誤代換）", parent=self
            )
            return
        self.result = WordEntry(
            word=word,
            enabled=self.enabled_var.get(),
            use_prompt=self.prompt_var.get(),
            fuzzy=self.fuzzy_var.get(),
        )
        self.destroy()


class RuleDialog(tk.Toplevel):
    """Modal dialog for adding/editing a ReplacementRule."""

    def __init__(self, parent: tk.Tk, title: str, rule: ReplacementRule | None = None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result: ReplacementRule | None = None

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="原文字：").grid(row=0, column=0, sticky="w")
        self.src_var = tk.StringVar(value=rule.src if rule else "")
        src_entry = ttk.Entry(body, textvariable=self.src_var, width=24)
        src_entry.grid(row=0, column=1, pady=4)

        ttk.Label(body, text="替換為：").grid(row=1, column=0, sticky="w")
        self.dst_var = tk.StringVar(value=rule.dst if rule else "")
        ttk.Entry(body, textvariable=self.dst_var, width=24).grid(row=1, column=1, pady=4)

        self.enabled_var = tk.BooleanVar(value=rule.enabled if rule else True)
        ttk.Checkbutton(body, text="啟用", variable=self.enabled_var).grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

        btns = ttk.Frame(body)
        btns.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="確定", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left")

        src_entry.focus_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    def _ok(self) -> None:
        src = self.src_var.get().strip()
        if not src:
            messagebox.showwarning("提示", "請輸入原文字", parent=self)
            return
        self.result = ReplacementRule(
            src=src, dst=self.dst_var.get().strip(), enabled=self.enabled_var.get()
        )
        self.destroy()
