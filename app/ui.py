import os
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from app.config import (
    DEFAULT_API_KEY_FILE,
    AppConfig,
    ModelSettings,
    load_app_config,
    normalize_chat_url,
    save_api_key,
    save_app_config,
)
from app.exporters import write_batch_workbook
from app.extractors.ai_vision import check_model_capabilities, safe_request_error
from app.services import process_batch, scan_pdf_files


ctk.set_default_color_theme("blue")


class PDFExtractorApp:
    def __init__(self, root: ctk.CTk | None = None) -> None:
        self.root = root or ctk.CTk()
        self.root.title("PDF 银行对账单整理工具")
        self.root.geometry("1060x780")
        self.root.minsize(900, 680)
        self.paths: list[Path] = []
        self.source_root: Path | None = None
        self.last_output_dir: Path | None = None
        self._processing_started: float | None = None
        self._stage_message = ""
        self._elapsed_timer = None
        self.config = load_app_config()

        ctk.set_appearance_mode("System")
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(4, weight=1)
        self._build_variables()
        self._build_header()
        self._build_source_card()
        self._build_model_card()
        self._build_action_card()
        self._build_log_card()

    def _build_variables(self) -> None:
        self.source_var = ctk.StringVar(value="尚未选择 PDF")
        self.count_var = ctk.StringVar(value="0 个文件")
        self.api_url_var = ctk.StringVar(value=self.config.api_url)
        self.model_name_var = ctk.StringVar(value=self.config.model_name)
        self.api_key_var = ctk.StringVar(value=self._load_saved_key())
        self.force_ai_var = ctk.BooleanVar(value=self.config.force_ai_mode)
        self.theme_var = ctk.StringVar(value="跟随系统")
        self.status_var = ctk.StringVar(value="等待开始")
        self.progress_var = ctk.StringVar(value="0 / 0")

    def _load_saved_key(self) -> str:
        path = Path(self.config.api_key_file_path) if self.config.api_key_file_path else DEFAULT_API_KEY_FILE
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _card(self, row: int, weight: int = 0) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self.root, corner_radius=12, border_width=1)
        card.grid(row=row, column=0, padx=18, pady=(0, 10), sticky="nsew" if weight else "ew")
        card.grid_columnconfigure(0, weight=1)
        if weight:
            card.grid_rowconfigure(1, weight=1)
        return card

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.grid(row=0, column=0, padx=22, pady=(16, 12), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="PDF 银行对账单整理工具",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")
        subtitle = ctk.CTkLabel(
            header,
            text="批量读取、逐份核对，并汇总为可追溯的 Excel",
            text_color=("#5B6573", "#AAB2BF"),
        )
        subtitle.grid(row=1, column=0, pady=(2, 0), sticky="w")

        theme = ctk.CTkOptionMenu(
            header,
            variable=self.theme_var,
            values=["跟随系统", "浅色", "深色"],
            width=112,
            command=self._change_theme,
        )
        theme.grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_source_card(self) -> None:
        card = self._card(1)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text="PDF 来源", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, padx=(16, 12), pady=14, sticky="w"
        )
        self.source_entry = ctk.CTkEntry(card, textvariable=self.source_var, height=36)
        self.source_entry.grid(row=0, column=1, padx=(0, 10), pady=12, sticky="ew")
        ctk.CTkButton(card, text="选择文件", width=92, height=36, command=self._choose_files).grid(
            row=0, column=2, padx=(0, 8), pady=12
        )
        ctk.CTkButton(card, text="选择文件夹", width=100, height=36, command=self._choose_folder).grid(
            row=0, column=3, padx=(0, 10), pady=12
        )
        ctk.CTkLabel(card, textvariable=self.count_var, width=78).grid(
            row=0, column=4, padx=(0, 16), pady=12
        )

    def _build_model_card(self) -> None:
        card = self._card(2)
        for column in (1, 3, 5):
            card.grid_columnconfigure(column, weight=1)

        ctk.CTkLabel(card, text="视觉模型兜底", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=7, padx=16, pady=(12, 7), sticky="w"
        )
        ctk.CTkLabel(card, text="接口地址").grid(row=1, column=0, padx=(16, 8), pady=(0, 13), sticky="w")
        ctk.CTkEntry(card, textvariable=self.api_url_var, height=34).grid(
            row=1, column=1, padx=(0, 14), pady=(0, 13), sticky="ew"
        )
        ctk.CTkLabel(card, text="API Key").grid(row=1, column=2, padx=(0, 8), pady=(0, 13), sticky="w")
        ctk.CTkEntry(card, textvariable=self.api_key_var, show="●", height=34).grid(
            row=1, column=3, padx=(0, 14), pady=(0, 13), sticky="ew"
        )
        ctk.CTkLabel(card, text="模型名称").grid(row=1, column=4, padx=(0, 8), pady=(0, 13), sticky="w")
        ctk.CTkEntry(card, textvariable=self.model_name_var, height=34).grid(
            row=1, column=5, padx=(0, 10), pady=(0, 13), sticky="ew"
        )
        self.test_button = ctk.CTkButton(
            card,
            text="测试连接",
            width=92,
            height=34,
            fg_color="transparent",
            border_width=1,
            text_color=("#1F5E91", "#7DB7E8"),
            command=self._start_capability_test,
        )
        self.test_button.grid(row=1, column=6, padx=(0, 16), pady=(0, 13))

    def _build_action_card(self) -> None:
        card = self._card(3)
        card.grid_columnconfigure(2, weight=1)
        self.start_button = ctk.CTkButton(
            card,
            text="开始整理",
            width=150,
            height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._start_processing,
        )
        self.start_button.grid(row=0, column=0, rowspan=2, padx=16, pady=14)

        ctk.CTkSwitch(card, text="强制使用视觉模型", variable=self.force_ai_var).grid(
            row=0, column=1, rowspan=2, padx=(0, 18), pady=14
        )
        ctk.CTkLabel(card, textvariable=self.status_var, anchor="w").grid(
            row=0, column=2, padx=(0, 10), pady=(12, 3), sticky="ew"
        )
        self.progress_bar = ctk.CTkProgressBar(card, height=13)
        self.progress_bar.grid(row=1, column=2, padx=(0, 10), pady=(3, 13), sticky="ew")
        self.progress_bar.set(0)
        ctk.CTkLabel(card, textvariable=self.progress_var, width=70).grid(
            row=0, column=3, rowspan=2, padx=(0, 8), pady=14
        )
        ctk.CTkButton(
            card,
            text="打开输出目录",
            width=112,
            height=34,
            fg_color="transparent",
            border_width=1,
            text_color=("#4B5563", "#C3CAD4"),
            command=self._open_output_folder,
        ).grid(row=0, column=4, rowspan=2, padx=(0, 16), pady=14)

    def _build_log_card(self) -> None:
        card = self._card(4, weight=1)
        ctk.CTkLabel(card, text="处理日志", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, padx=16, pady=(12, 7), sticky="w"
        )
        self.log_box = ctk.CTkTextbox(card, wrap="word", corner_radius=8)
        self.log_box.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self._log("请选择 PDF 文件或文件夹。")
        if self.force_ai_var.get():
            self._log("当前保存为强制视觉模式，会跳过本地读取。关闭“强制使用视觉模型”可先尝试本地文字提取。")

    def _change_theme(self, choice: str) -> None:
        modes = {"跟随系统": "System", "浅色": "Light", "深色": "Dark"}
        ctk.set_appearance_mode(modes[choice])

    def _choose_files(self) -> None:
        selected = filedialog.askopenfilenames(
            title="选择银行对账单 PDF",
            filetypes=[("PDF 文件", "*.pdf")],
        )
        if not selected:
            return
        self.paths = [Path(path) for path in selected]
        common = os.path.commonpath([str(path.parent) for path in self.paths])
        self.source_root = Path(common)
        self.source_var.set("；".join(str(path) for path in self.paths))
        self._show_selection()

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择包含银行对账单的文件夹")
        if not selected:
            return
        self.source_root = Path(selected)
        self.paths = scan_pdf_files(self.source_root)
        self.source_var.set(str(self.source_root))
        self._show_selection()

    def _show_selection(self) -> None:
        self.count_var.set(f"{len(self.paths)} 个文件")
        self._log(f"已选择 {len(self.paths)} 个 PDF。")

    def _read_settings(self) -> ModelSettings:
        return ModelSettings(
            api_url=normalize_chat_url(self.api_url_var.get()),
            model_name=self.model_name_var.get().strip(),
            api_key=self.api_key_var.get().strip(),
        )

    def _save_settings(self) -> ModelSettings:
        settings = self._read_settings()
        key_path = save_api_key(settings.api_key)
        self.config = AppConfig(
            api_url=self.api_url_var.get().strip(),
            model_name=settings.model_name,
            api_key_file_path=str(key_path),
            force_ai_mode=bool(self.force_ai_var.get()),
        )
        save_app_config(self.config)
        return settings

    def _start_capability_test(self) -> None:
        settings = self._save_settings()
        if not settings.api_url or not settings.model_name:
            messagebox.showwarning("信息不完整", "请先填写接口地址和模型名称。")
            return
        self.test_button.configure(state="disabled", text="测试中…")
        self._log("开始测试接口、模型和图片能力。")
        threading.Thread(target=self._capability_worker, args=(settings,), daemon=True).start()

    def _capability_worker(self, settings: ModelSettings) -> None:
        report = check_model_capabilities(settings)
        lines = [
            f"接口连通：{'通过' if report.endpoint_reachable else '失败'}",
            f"模型可调用：{'通过' if report.model_callable else '失败'}",
            f"图片能力：{'通过' if report.vision_capable else '失败'}",
        ]
        lines.extend(report.messages)
        self.root.after(0, self._finish_capability_test, lines)

    def _finish_capability_test(self, lines: list[str]) -> None:
        for line in lines:
            self._log(line)
        self.test_button.configure(state="normal", text="测试连接")

    def _start_processing(self) -> None:
        if not self.paths or self.source_root is None:
            messagebox.showwarning("尚未选择文件", "请先选择 PDF 文件或文件夹。")
            return
        settings = self._save_settings()
        active_settings = settings if settings.api_url and settings.model_name else None
        if self.force_ai_var.get() and active_settings is None:
            messagebox.showwarning("模型未配置", "强制模型模式需要填写接口地址和模型名称。")
            return

        self.start_button.configure(state="disabled", text="处理中…")
        self.progress_bar.set(0)
        self.progress_var.set(f"0 / {len(self.paths)}")
        self.status_var.set("正在准备")
        mode = "强制视觉：跳过本地读取" if self.force_ai_var.get() else (
            "本地优先，核对未通过时自动使用视觉模型" if active_settings else "仅本地读取，未配置视觉模型"
        )
        self._log(f"开始逐份读取并核对 PDF。当前模式：{mode}。")
        self._processing_started = time.monotonic()
        self._stage_message = "正在准备"
        self._refresh_elapsed()
        threading.Thread(
            target=self._process_worker,
            args=(active_settings, bool(self.force_ai_var.get())),
            daemon=True,
        ).start()

    def _process_worker(self, settings: ModelSettings | None, force_ai: bool) -> None:
        try:
            batch = process_batch(self.paths, settings, force_ai, progress=self._progress_from_worker)
            output_path = write_batch_workbook(batch, self.source_root)
            self.root.after(0, self._finish_processing, batch, output_path)
        except Exception as exc:
            safe_message = safe_request_error(exc, settings) if settings else str(exc)
            self.root.after(0, self._fail_processing, safe_message)

    def _progress_from_worker(self, current: int, total: int, message: str) -> None:
        self.root.after(0, self._show_progress, current, total, message)

    def _show_progress(self, current: int, total: int, message: str) -> None:
        self.progress_bar.set(current / total if total else 0)
        self.progress_var.set(f"{current} / {total}")
        self._stage_message = message
        self.status_var.set(message)
        self._log(message)

    def _refresh_elapsed(self) -> None:
        if self._processing_started is None:
            return
        seconds = int(time.monotonic() - self._processing_started)
        self.status_var.set(f"{self._stage_message}（已用 {seconds // 60}分{seconds % 60:02d}秒）")
        self._elapsed_timer = self.root.after(1000, self._refresh_elapsed)

    def _stop_elapsed(self) -> None:
        self._processing_started = None
        if self._elapsed_timer is not None:
            self.root.after_cancel(self._elapsed_timer)
            self._elapsed_timer = None

    def _finish_processing(self, batch, output_path: Path) -> None:
        self._stop_elapsed()
        self.last_output_dir = output_path.parent
        passed = sum(item.validation.status == "通过" for item in batch.statements)
        zero = sum(item.validation.status == "零交易通过" for item in batch.statements)
        failed = sum(item.validation.status == "核对失败" for item in batch.statements)
        self._log(f"处理完成：通过 {passed} 份，零交易 {zero} 份，失败 {failed} 份。")
        from app.对账单控制信息 import statement_links
        links = statement_links(batch)
        unchecked = sum("未检查" in row["检查结果"] for row in links)
        issues = sum(any(word in row["检查结果"] for word in ("缺期", "重叠", "不一致", "倒置")) for row in links)
        self._log(f"期间衔接另行检查，有问题 {issues} 项，未检查 {unchecked} 项，详见期间衔接检查表。")
        missing_controls = sum(any(check["status"] == "未检查" for check in item.validation.control_checks.values()) for item in batch.statements)
        if missing_controls:
            self._log(f"{missing_controls} 份存在未执行的控制余额项目，详见提取汇总。")
        self._log(f"输出文件：{output_path}")
        for statement in batch.statements:
            if statement.validation.warnings:
                self._log(f"{statement.source_path.name}：核对依据={statement.validation.validation_basis}；{'；'.join(statement.validation.warnings)}")
            if statement.validation.status == "核对失败":
                self._log(f"{statement.source_path.name}：{'；'.join(statement.validation.errors)}")
        self.status_var.set("处理完成")
        self.start_button.configure(state="normal", text="开始整理")
        messagebox.showinfo("处理完成", f"Excel 已生成：\n{output_path}")

    def _fail_processing(self, message: str) -> None:
        self._stop_elapsed()
        self._log(f"处理未完成：{message}")
        self.status_var.set("处理失败")
        self.start_button.configure(state="normal", text="开始整理")
        messagebox.showerror("处理失败", message)

    def _open_output_folder(self) -> None:
        output_dir = self.last_output_dir
        if output_dir is None and self.source_root is not None:
            output_dir = self.source_root / "提取结果"
        if output_dir is None or not output_dir.exists():
            messagebox.showinfo("暂无输出", "尚未生成输出文件。")
            return
        os.startfile(output_dir)

    def _log(self, message: str) -> None:
        self.log_box.insert("end", message.rstrip() + "\n")
        self.log_box.see("end")

    def run(self) -> None:
        self.root.mainloop()
