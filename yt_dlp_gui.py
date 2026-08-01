from __future__ import annotations

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import sqlite3
import tempfile
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled
except ImportError:
    yt_dlp = None

APP_NAME = "YT-DLP GUI"
APP_VERSION = "1.0.0"
PROJECT_URL = "https://github.com/yt-dlp/yt-dlp"


@dataclass(frozen=True)
class DownloadSettings:
    url: str
    output_dir: Path
    media_type: str
    video_quality: str
    audio_format: str
    playlist: bool
    subtitles: bool
    thumbnail: bool
    metadata: bool
    restrict_names: bool
    browser: str
    concurrent_fragments: int
    cookiefile: str | None


class GuiLogger:
    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue

    def debug(self, msg: str) -> None:
        # yt-dlp envia várias mensagens normais por debug.
        if msg.startswith("[debug]"):
            return
        self.event_queue.put(("log", msg))

    def warning(self, msg: str) -> None:
        self.event_queue.put(("log", f"AVISO: {msg}"))

    def error(self, msg: str) -> None:
        self.event_queue.put(("log", f"ERRO: {msg}"))


class YtDlpGui(tk.Tk):
    QUALITY_MAP = {
        "Melhor disponível": "bestvideo+bestaudio/best",
        "Até 2160p (4K)": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
        "Até 1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best",
        "Até 1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "Até 720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "Até 480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
        "Até 360p": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
    }

    BROWSERS = {
        "Não usar": "",
        "Chrome": "chrome",
        "Chromium": "chromium",
        "Edge": "edge",
        "Firefox": "firefox",
        "Opera": "opera",
        "Brave": "brave",
        "Vivaldi": "vivaldi",
        "Safari": "safari",
    }

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("940x710")
        self.minsize(780, 620)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.event_queue: queue.Queue = queue.Queue()
        self.download_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.last_output_dir = Path.home() / "Downloads"
        self.current_percent = 0.0

        self._configure_style()
        self._create_variables()
        self._build_ui()
        self._update_media_controls()
        # Start periodic FFmpeg availability checks
        self.after(1000, self._update_ffmpeg_status)
        self.after(100, self._process_events)

        if yt_dlp is None:
            self.after(250, self._show_missing_dependency)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        elif "clam" in available:
            style.theme_use("clam")

        style.configure("Header.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subheader.TLabel", font=("Segoe UI", 10))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("Danger.TButton", padding=(12, 8))

    def _create_variables(self) -> None:
        self.url_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(self.last_output_dir))
        self.media_type_var = tk.StringVar(value="Vídeo")
        self.quality_var = tk.StringVar(value="Até 1080p")
        self.audio_format_var = tk.StringVar(value="mp3")
        self.playlist_var = tk.BooleanVar(value=False)
        self.subtitles_var = tk.BooleanVar(value=False)
        self.thumbnail_var = tk.BooleanVar(value=False)
        self.metadata_var = tk.BooleanVar(value=True)
        self.restrict_names_var = tk.BooleanVar(value=False)
        self.browser_var = tk.StringVar(value="Não usar")
        self.fragments_var = tk.IntVar(value=4)
        self.status_var = tk.StringVar(value="Pronto")
        self.detail_var = tk.StringVar(value="Cole uma URL para começar.")
        self.speed_var = tk.StringVar(value="")
        self.eta_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.cookiefile_var = tk.StringVar(value="")
        # temporary cookiefile created when copying browser DB
        self._temp_cookiefile: str | None = None
        # Flag to avoid overlapping FFmpeg checks
        self.ffmpeg_check_running = False

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=18)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text=APP_NAME, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Interface gráfica para baixar vídeos e áudios usando yt-dlp",
            style="Subheader.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(header, text="Projeto yt-dlp", command=lambda: webbrowser.open(PROJECT_URL)).grid(
            row=0, column=1, rowspan=2, padx=(10, 0)
        )

        source = ttk.LabelFrame(main, text="Origem", padding=12, style="Section.TLabelframe")
        source.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(1, weight=1)

        ttk.Label(source, text="URL:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.url_entry = ttk.Entry(source, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda _event: self.start_download())
        ttk.Button(source, text="Colar", command=self.paste_url).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(source, text="Salvar em:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Entry(source, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(source, text="Procurar", command=self.choose_output_dir).grid(
            row=1, column=2, padx=(8, 0), pady=(10, 0)
        )

        settings = ttk.LabelFrame(main, text="Configurações", padding=12, style="Section.TLabelframe")
        settings.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            settings.columnconfigure(column, weight=1)

        ttk.Label(settings, text="Tipo:").grid(row=0, column=0, sticky="w")
        media_box = ttk.Combobox(
            settings,
            textvariable=self.media_type_var,
            values=("Vídeo", "Somente áudio"),
            state="readonly",
            width=20,
        )
        media_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        media_box.bind("<<ComboboxSelected>>", lambda _event: self._update_media_controls())

        ttk.Label(settings, text="Qualidade do vídeo:").grid(row=0, column=1, sticky="w")
        self.quality_box = ttk.Combobox(
            settings,
            textvariable=self.quality_var,
            values=tuple(self.QUALITY_MAP),
            state="readonly",
            width=22,
        )
        self.quality_box.grid(row=1, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(settings, text="Formato de áudio:").grid(row=0, column=2, sticky="w")
        self.audio_box = ttk.Combobox(
            settings,
            textvariable=self.audio_format_var,
            values=("mp3", "m4a", "opus", "wav", "flac"),
            state="readonly",
            width=14,
        )
        self.audio_box.grid(row=1, column=2, sticky="ew", padx=(0, 8))

        ttk.Label(settings, text="Cookies do navegador:").grid(row=0, column=3, sticky="w")
        ttk.Combobox(
            settings,
            textvariable=self.browser_var,
            values=tuple(self.BROWSERS),
            state="readonly",
            width=18,
        ).grid(row=1, column=3, sticky="ew")

        # Cookie file selector
        ttk.Label(settings, text="Arquivo de cookies opcional:").grid(row=2, column=3, sticky="w", pady=(8,0))
        cookie_frame = ttk.Frame(settings)
        cookie_frame.grid(row=3, column=3, sticky="ew")
        ttk.Entry(cookie_frame, textvariable=self.cookiefile_var, width=22).pack(side="left", fill="x", expand=True)
        ttk.Button(cookie_frame, text="Selecionar", command=self.choose_cookie_file).pack(side="left", padx=(6,0))

        options = ttk.Frame(settings)
        options.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(13, 0))
        for column in range(4):
            options.columnconfigure(column, weight=1)

        ttk.Checkbutton(options, text="Baixar playlist completa", variable=self.playlist_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(options, text="Baixar legendas", variable=self.subtitles_var).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Checkbutton(options, text="Salvar miniatura", variable=self.thumbnail_var).grid(
            row=0, column=2, sticky="w"
        )
        ttk.Checkbutton(options, text="Incorporar metadados", variable=self.metadata_var).grid(
            row=0, column=3, sticky="w"
        )
        ttk.Checkbutton(options, text="Nomes compatíveis com Windows", variable=self.restrict_names_var).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

        fragment_frame = ttk.Frame(options)
        fragment_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(fragment_frame, text="Fragmentos simultâneos:").pack(side="left")
        ttk.Spinbox(
            fragment_frame,
            from_=1,
            to=16,
            textvariable=self.fragments_var,
            width=5,
        ).pack(side="left", padx=(6, 0))

        # FFmpeg status indicator (will be updated periodically)
        ffmpeg_frame = ttk.Frame(settings)
        ffmpeg_frame.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(ffmpeg_frame, text="FFmpeg:").pack(side="left", padx=(0, 6))
        self.ffmpeg_status_label = tk.Label(ffmpeg_frame, text="Verificando...", bg="gray", fg="white", padx=8)
        self.ffmpeg_status_label.pack(side="left")

        controls = ttk.Frame(main)
        controls.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        controls.columnconfigure(0, weight=1)

        buttons = ttk.Frame(controls)
        buttons.grid(row=0, column=0, sticky="w")
        self.download_button = ttk.Button(
            buttons, text="Baixar", style="Primary.TButton", command=self.start_download
        )
        self.download_button.pack(side="left")
        self.cancel_button = ttk.Button(
            buttons,
            text="Cancelar",
            style="Danger.TButton",
            command=self.cancel_download,
            state="disabled",
        )
        self.cancel_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Abrir pasta", command=self.open_output_dir).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Limpar log", command=self.clear_log).pack(side="left", padx=(8, 0))

        progress = ttk.LabelFrame(main, text="Progresso", padding=12, style="Section.TLabelframe")
        progress.grid(row=4, column=0, sticky="nsew")
        progress.columnconfigure(0, weight=1)
        progress.rowconfigure(4, weight=1)

        status_line = ttk.Frame(progress)
        status_line.grid(row=0, column=0, sticky="ew")
        status_line.columnconfigure(0, weight=1)
        ttk.Label(status_line, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(status_line, textvariable=self.speed_var).grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Label(status_line, textvariable=self.eta_var).grid(row=0, column=2, sticky="e", padx=(12, 0))

        ttk.Progressbar(
            progress, variable=self.progress_var, maximum=100, mode="determinate"
        ).grid(row=1, column=0, sticky="ew", pady=(8, 0))

        ttk.Label(progress, textvariable=self.detail_var, wraplength=850).grid(
            row=2, column=0, sticky="w", pady=(7, 8)
        )

        log_frame = ttk.Frame(progress)
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            height=12,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Label(
            main,
            text="Baixe apenas conteúdo que você tem autorização para acessar e salvar.",
            anchor="center",
        )
        footer.grid(row=5, column=0, sticky="ew", pady=(10, 0))

    def _show_missing_dependency(self) -> None:
        messagebox.showerror(
            "Dependência ausente",
            "O módulo yt-dlp não foi encontrado.\n\n"
            "Instale com:\npython -m pip install -U yt-dlp",
        )
        self._append_log("Dependência ausente: instale yt-dlp com pip.")

    def _update_media_controls(self) -> None:
        audio_only = self.media_type_var.get() == "Somente áudio"
        self.quality_box.configure(state="disabled" if audio_only else "readonly")
        self.audio_box.configure(state="readonly" if audio_only else "disabled")

    def paste_url(self) -> None:
        try:
            clipboard = self.clipboard_get().strip()
        except tk.TclError:
            clipboard = ""
        if clipboard:
            self.url_var.set(clipboard)

    def choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.home()))
        if selected:
            self.output_var.set(selected)

    def open_output_dir(self) -> None:
        output_dir = Path(self.output_var.get()).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(output_dir)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(output_dir)])
        except Exception as exc:
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta:\n{exc}")

    def choose_cookie_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o arquivo SQLite de cookies (ex.: Cookies)",
            filetypes=(("SQLite files", "*.sqlite;*.db;*"), ("All files", "*.*")),
            initialdir=str(Path.home()),
        )
        if selected:
            self.cookiefile_var.set(selected)

    def _find_chrome_like_cookie_file(self, browser: str) -> str | None:
        # Search common locations for Chrome/Edge-like cookie DBs
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not local:
            return None
        candidates = []
        # Map browser key to base folder names
        mapping = {
            "chrome": os.path.join(local, "Google", "Chrome", "User Data"),
            "edge": os.path.join(local, "Microsoft", "Edge", "User Data"),
            "chromium": os.path.join(local, "Chromium", "User Data"),
            "brave": os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"),
            "vivaldi": os.path.join(local, "Vivaldi", "User Data"),
        }
        base = mapping.get(browser)
        if base and os.path.isdir(base):
            # check Default and common profiles
            for profile in ("Default", "Profile 1", "Profile 2"):
                p = os.path.join(base, profile, "Cookies")
                if os.path.isfile(p):
                    candidates.append(p)
            # also check any directory under base
            try:
                for name in os.listdir(base):
                    p = os.path.join(base, name, "Cookies")
                    if os.path.isfile(p):
                        candidates.append(p)
            except Exception:
                pass

        return candidates[0] if candidates else None

    def _copy_sqlite_db_with_backup(self, src: str) -> str | None:
        # Try to create a consistent copy using sqlite3 backup API; fallback to shutil.copy2
        try:
            if not os.path.isfile(src):
                return None
            dest = tempfile.NamedTemporaryFile(prefix="yt_dlp_cookies_", delete=False).name
            try:
                # open destination DB
                dest_conn = sqlite3.connect(dest)
                try:
                    # try to open src in read-only URI mode
                    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
                except sqlite3.OperationalError:
                    dest_conn.close()
                    # fallback to raw copy
                    shutil.copy2(src, dest)
                    return dest
                try:
                    with src_conn:
                        src_conn.backup(dest_conn)
                    return dest
                finally:
                    try:
                        src_conn.close()
                    except Exception:
                        pass
                    try:
                        dest_conn.close()
                    except Exception:
                        pass
            except Exception:
                # fallback to copy
                try:
                    shutil.copy2(src, dest)
                    return dest
                except Exception:
                    try:
                        if os.path.exists(dest):
                            os.remove(dest)
                    except Exception:
                        pass
                    return None
        except Exception:
            return None

    def _on_detect_cookies(self) -> None:
        # Run detection in background to avoid UI freeze
        def _job():
            path = self._find_opera_cookie_file()
            if path:
                try:
                    self.after(0, lambda: self.cookiefile_var.set(path))
                    self.event_queue.put(("log", f"Detectado cookie do Opera: {path}"))
                except Exception:
                    pass
            else:
                self.event_queue.put(("log", "Não foi possível detectar automaticamente o arquivo de cookies do Opera."))

        threading.Thread(target=_job, daemon=True).start()

    def _find_opera_cookie_file(self) -> str | None:
        # Common Opera profile locations to check
        candidates: list[str] = []
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")
        def check_base(base: str) -> None:
            try:
                if not base or not os.path.isdir(base):
                    return
                for name in os.listdir(base):
                    possible = os.path.join(base, name, "Cookies")
                    if os.path.isfile(possible):
                        candidates.append(possible)
            except Exception:
                pass

        # Typical Opera roaming profile
        if appdata:
            check_base(os.path.join(appdata, "Opera Software"))
        # Also check LOCALAPPDATA
        if localappdata:
            check_base(os.path.join(localappdata, "Opera Software"))

        # As a fallback, search a few known subpaths
        known_paths = [
            os.path.join(appdata or "", "Opera Software", "Opera Stable", "Cookies"),
            os.path.join(appdata or "", "Opera Software", "Opera GX Stable", "Cookies"),
            os.path.join(appdata or "", "Opera Software", "Opera Air Stable", "Cookies"),
            # also check localappdata variants
            os.path.join(localappdata or "", "Opera Software", "Opera Stable", "Cookies"),
            os.path.join(localappdata or "", "Opera Software", "Opera GX Stable", "Cookies"),
            os.path.join(localappdata or "", "Opera Software", "Opera Air Stable", "Cookies"),
        ]
        for p in known_paths:
            if p and os.path.isfile(p):
                candidates.insert(0, p)

        return candidates[0] if candidates else None

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        if not text:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _collect_settings(self) -> DownloadSettings | None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL necessária", "Cole o endereço do vídeo ou da playlist.")
            self.url_entry.focus_set()
            return None

        output_dir = Path(self.output_var.get()).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Pasta inválida", f"Não foi possível preparar a pasta:\n{exc}")
            return None

        try:
            fragments = max(1, min(16, int(self.fragments_var.get())))
        except (tk.TclError, ValueError):
            fragments = 4

        return DownloadSettings(
            url=url,
            output_dir=output_dir,
            media_type=self.media_type_var.get(),
            video_quality=self.quality_var.get(),
            audio_format=self.audio_format_var.get(),
            playlist=self.playlist_var.get(),
            subtitles=self.subtitles_var.get(),
            thumbnail=self.thumbnail_var.get(),
            metadata=self.metadata_var.get(),
            restrict_names=self.restrict_names_var.get(),
            browser=self.BROWSERS.get(self.browser_var.get(), ""),
            concurrent_fragments=fragments,
            cookiefile=self.cookiefile_var.get() or None,
        )

    def start_download(self) -> None:
        if self.download_thread and self.download_thread.is_alive():
            return
        if yt_dlp is None:
            self._show_missing_dependency()
            return

        settings = self._collect_settings()
        if settings is None:
            return

        if settings.media_type == "Somente áudio" and not self._ffmpeg_available():
            proceed = messagebox.askyesno(
                "FFmpeg não encontrado",
                "A conversão para áudio normalmente exige o FFmpeg.\n"
                "O download pode falhar ou não ser convertido.\n\nContinuar mesmo assim?",
            )
            if not proceed:
                return

        self.cancel_event.clear()
        self.current_percent = 0
        self.progress_var.set(0)
        self.status_var.set("Preparando...")
        self.detail_var.set(settings.url)
        self.speed_var.set("")
        self.eta_var.set("")
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._append_log(f"Iniciando: {settings.url}")

        self.download_thread = threading.Thread(
            target=self._download_worker,
            args=(settings,),
            daemon=True,
        )
        self.download_thread.start()

    def cancel_download(self) -> None:
        if self.download_thread and self.download_thread.is_alive():
            self.cancel_event.set()
            self.status_var.set("Cancelando...")
            self.detail_var.set("Aguardando o yt-dlp encerrar com segurança.")
            self.cancel_button.configure(state="disabled")

    def _ffmpeg_available(self) -> bool:
        path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if not path:
            return False

        try:
            if sys.platform.startswith("win"):
                # Evitar janela de erro do Windows ao executar um ffmpeg corrompido.
                SEM_FAILCRITICALERRORS = 0x0001
                SEM_NOGPFAULTERRORBOX = 0x0002
                old_error_mode = ctypes.windll.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX)
                try:
                    subprocess.run(
                        [path, "-version"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True,
                        timeout=5,
                    )
                finally:
                    ctypes.windll.kernel32.SetErrorMode(old_error_mode)
            else:
                subprocess.run(
                    [path, "-version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=5,
                )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False

    def _update_ffmpeg_status(self) -> None:
        # Run the potentially-blocking ffmpeg check in a background thread
        if getattr(self, "ffmpeg_check_running", False):
            # Already running; schedule next check later
            try:
                self.after(5000, self._update_ffmpeg_status)
            except Exception:
                pass
            return

        def _worker() -> None:
            try:
                available = self._ffmpeg_available()
                # update UI in main thread
                try:
                    self.after(0, lambda: self._apply_ffmpeg_status(available))
                except Exception:
                    pass
            finally:
                self.ffmpeg_check_running = False

        self.ffmpeg_check_running = True
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        # note: do not reschedule here — run check only once at startup

    def _apply_ffmpeg_status(self, available: bool) -> None:
        try:
            if available:
                self.ffmpeg_status_label.config(text="Instalado", bg="#2e7d32")
            else:
                self.ffmpeg_status_label.config(text="Ausente", bg="#b71c1c")
        except Exception:
            try:
                self.ffmpeg_status_label.config(text="Erro", bg="gray")
            except Exception:
                pass

    def _build_options(self, settings: DownloadSettings) -> dict[str, Any]:
        playlist_template = (
            "%(playlist_title|Playlist)s/%(playlist_index)03d - %(title)s [%(id)s].%(ext)s"
        )
        single_template = "%(title)s [%(id)s].%(ext)s"
        outtmpl = str(settings.output_dir / (playlist_template if settings.playlist else single_template))

        options: dict[str, Any] = {
            "outtmpl": outtmpl,
            "noplaylist": not settings.playlist,
            "ignoreerrors": False,
            "continuedl": True,
            "overwrites": False,
            "windowsfilenames": settings.restrict_names,
            "concurrent_fragment_downloads": settings.concurrent_fragments,
            "progress_hooks": [self._progress_hook],
            "logger": GuiLogger(self.event_queue),
            "quiet": True,
            "no_warnings": False,
            "retries": 10,
            "fragment_retries": 10,
            "file_access_retries": 3,
            "extractor_retries": 3,
        }

        ffmpeg_available = self._ffmpeg_available()

        if settings.media_type == "Somente áudio":
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": settings.audio_format,
                    "preferredquality": "0",
                }
            ]
        else:
            if ffmpeg_available:
                options["format"] = self.QUALITY_MAP.get(
                    settings.video_quality,
                    self.QUALITY_MAP["Até 1080p"],
                )
                options["merge_output_format"] = "mp4"
            else:
                fallback_quality = {
                    "Melhor disponível": "best",
                    "Até 2160p (4K)": "best[height<=2160]",
                    "Até 1440p": "best[height<=1440]",
                    "Até 1080p": "best[height<=1080]",
                    "Até 720p": "best[height<=720]",
                    "Até 480p": "best[height<=480]",
                    "Até 360p": "best[height<=360]",
                }
                options["format"] = fallback_quality.get(
                    settings.video_quality,
                    "best",
                )

        postprocessors = options.setdefault("postprocessors", [])

        if settings.metadata and ffmpeg_available:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            options["embed_metadata"] = True

        if settings.thumbnail:
            options["writethumbnail"] = True
            # Compatibilidade visual em arquivos de áudio e vídeo.
            if ffmpeg_available:
                postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

        if settings.subtitles:
            options.update(
                {
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": ["pt-BR", "pt", "en"],
                    "subtitlesformat": "best",
                    "embedsubtitles": settings.media_type == "Vídeo" and ffmpeg_available,
                }
            )

        if settings.browser:
            # If user provided a cookie file explicitly, prefer that
            if settings.cookiefile:
                options["cookiefile"] = settings.cookiefile
            else:
                # Try to copy browser cookie DB to a temporary file first (mitigates locked DB copy errors)
                try_path = None
                try:
                    try_path = self._find_chrome_like_cookie_file(settings.browser)
                except Exception:
                    try_path = None

                copied = None
                if try_path:
                    copied = self._copy_sqlite_db_with_backup(try_path)

                if copied:
                    options["cookiefile"] = copied
                    # remember to clean up after download
                    self._temp_cookiefile = copied
                    self.event_queue.put(("log", f"Usando cópia temporária do cookie: {copied}"))
                else:
                    options["cookiesfrombrowser"] = (settings.browser,)

        # Debug info to help diagnose format/ffmpeg issues
        try:
            self.event_queue.put(("log", f"DEBUG: ffmpeg_available={ffmpeg_available}, format={options.get('format')}"))
        except Exception:
            pass

        return options

    def _download_worker(self, settings: DownloadSettings) -> None:
        try:
            options = self._build_options(settings)
            with yt_dlp.YoutubeDL(options) as downloader:
                error_code = downloader.download([settings.url])

            if self.cancel_event.is_set():
                self.event_queue.put(("cancelled", None))
            elif error_code:
                self.event_queue.put(("error", f"yt-dlp terminou com o código {error_code}."))
            else:
                self.event_queue.put(("complete", str(settings.output_dir)))
        except DownloadCancelled:
            self.event_queue.put(("cancelled", None))
        except Exception as exc:
            if self.cancel_event.is_set():
                self.event_queue.put(("cancelled", None))
            else:
                msg = str(exc)
                lower = msg.lower()
                # Detect common yt-dlp cookie DB copy failure (Edge/Chrome)
                if ("could not copy" in lower and "cookie" in lower) or "could not not copy chrome cookie database" in lower:
                    friendly = (
                        "Falha ao acessar o banco de cookies do navegador.\n\n"
                        "Feche o navegador (Edge/Chrome/Chromium) e tente novamente,\n"
                        "ou clique em 'Selecionar' e aponte para o arquivo de cookies manualmente.\n\n"
                        "Mais informações: https://github.com/yt-dlp/yt-dlp/issues/7271"
                    )
                    self.event_queue.put(("error", friendly))
                else:
                    self.event_queue.put(("error", msg))
        finally:
            # cleanup temporary cookie DB if we created one
            try:
                tmp = getattr(self, "_temp_cookiefile", None)
                if tmp:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                            self.event_queue.put(("log", f"Arquivo de cookie temporário removido: {tmp}"))
                    except Exception:
                        pass
                    self._temp_cookiefile = None
            except Exception:
                pass

    def _progress_hook(self, data: dict[str, Any]) -> None:
        if self.cancel_event.is_set():
            raise DownloadCancelled("Download cancelado pelo usuário")

        status = data.get("status")
        info = data.get("info_dict") or {}
        filename = data.get("filename") or info.get("_filename") or info.get("title") or ""

        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = (downloaded / total * 100) if total else self.current_percent
            self.current_percent = max(self.current_percent, min(100.0, percent))

            payload = {
                "percent": self.current_percent,
                "filename": Path(str(filename)).name,
                "speed": self._format_speed(data.get("speed")),
                "eta": self._format_eta(data.get("eta")),
                "downloaded": self._format_bytes(downloaded),
                "total": self._format_bytes(total) if total else "desconhecido",
            }
            self.event_queue.put(("progress", payload))

        elif status == "finished":
            self.current_percent = 100.0
            self.event_queue.put(
                (
                    "finished_file",
                    {
                        "filename": Path(str(filename)).name,
                        "message": "Download concluído; processando o arquivo...",
                    },
                )
            )

        elif status == "error":
            self.event_queue.put(("log", f"Falha no download: {filename}"))

    @staticmethod
    def _format_bytes(value: float | int | None) -> str:
        if not value:
            return "0 B"
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @classmethod
    def _format_speed(cls, value: float | int | None) -> str:
        return f"Velocidade: {cls._format_bytes(value)}/s" if value else ""

    @staticmethod
    def _format_eta(value: float | int | None) -> str:
        if value is None:
            return ""
        seconds = max(0, int(value))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            text = f"{minutes:02d}:{seconds:02d}"
        return f"Restante: {text}"

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.event_queue.get_nowait()
                if event == "log":
                    self._append_log(str(payload))
                elif event == "progress":
                    self.progress_var.set(payload["percent"])
                    self.status_var.set(f"Baixando... {payload['percent']:.1f}%")
                    self.detail_var.set(
                        f"{payload['filename']} — {payload['downloaded']} de {payload['total']}"
                    )
                    self.speed_var.set(payload["speed"])
                    self.eta_var.set(payload["eta"])
                elif event == "finished_file":
                    self.progress_var.set(100)
                    self.status_var.set("Processando...")
                    self.detail_var.set(payload["message"])
                    self._append_log(f"Arquivo baixado: {payload['filename']}")
                elif event == "complete":
                    self.progress_var.set(100)
                    self.status_var.set("Concluído")
                    self.detail_var.set(f"Arquivos salvos em: {payload}")
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self._append_log("Download finalizado com sucesso.")
                    self._set_idle()
                    self.bell()
                elif event == "cancelled":
                    self.status_var.set("Cancelado")
                    self.detail_var.set("O download foi cancelado.")
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self._append_log("Download cancelado pelo usuário.")
                    self._set_idle()
                elif event == "error":
                    self.status_var.set("Erro")
                    self.detail_var.set(str(payload))
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self._append_log(f"Erro: {payload}")
                    self._set_idle()
                    messagebox.showerror("Falha no download", str(payload))
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_events)

    def _set_idle(self) -> None:
        self.download_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

    def on_close(self) -> None:
        if self.download_thread and self.download_thread.is_alive():
            close = messagebox.askyesno(
                "Download em andamento",
                "Há um download em andamento. Deseja cancelar e fechar?",
            )
            if not close:
                return
            self.cancel_event.set()
        self.destroy()


def main() -> None:
    app = YtDlpGui()
    app.mainloop()


if __name__ == "__main__":
    main()
