#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Import de dump MySQL (.sql, .sql.gz, .tar.gz/.tgz) avec fenêtre et pourcentage.

Équivalent graphique de :
    pv 206364_SMN.sql | mysql -u root -pxxxx --reconnect RecylogSMN

Prérequis : Python 3 (tkinter inclus) + le client "mysql" installé (dans le PATH
ou à indiquer dans la fenêtre). Aucune bibliothèque Python externe.
"""

import gzip
import os
import queue
import re
import shutil
import subprocess
import tarfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

CHUNK = 1024 * 1024  # 1 Mo
NEW_DB_LABEL = "<< Nouvelle base >>"


def fmt_size(n):
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} To"


def fmt_time(s):
    s = int(s)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Import MySQL")
        self.resizable(False, False)
        self.q = queue.Queue()
        self.proc = None
        self.cancel_evt = threading.Event()
        self.running = False

        self.v_mysql = tk.StringVar(value=shutil.which("mysql") or "mysql")
        self.v_host = tk.StringVar(value="localhost")
        self.v_port = tk.StringVar(value="3306")
        self.v_user = tk.StringVar(value="root")
        self.v_pass = tk.StringVar()
        self.v_file = tk.StringVar()
        self.v_mode = tk.StringVar(value="existing")
        self.v_db = tk.StringVar()
        self.v_newdb = tk.StringVar()
        self.v_reconnect = tk.BooleanVar(value=True)
        self.v_force = tk.BooleanVar(value=False)
        self.v_charset = tk.StringVar(value="")

        self._build()
        self.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = {"padx": 6, "pady": 3}

        # Connexion
        f1 = ttk.LabelFrame(self, text="Connexion MySQL")
        f1.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ttk.Label(f1, text="Client mysql :").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(f1, textvariable=self.v_mysql, width=38).grid(row=0, column=1, columnspan=3, sticky="ew", **pad)
        ttk.Button(f1, text="...", width=3, command=self._browse_mysql).grid(row=0, column=4, **pad)

        ttk.Label(f1, text="Hôte :").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(f1, textvariable=self.v_host, width=18).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(f1, text="Port :").grid(row=1, column=2, sticky="e", **pad)
        ttk.Entry(f1, textvariable=self.v_port, width=7).grid(row=1, column=3, sticky="w", **pad)

        ttk.Label(f1, text="Utilisateur :").grid(row=2, column=0, sticky="e", **pad)
        ttk.Entry(f1, textvariable=self.v_user, width=18).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(f1, text="Mot de passe :").grid(row=2, column=2, sticky="e", **pad)
        e = ttk.Entry(f1, textvariable=self.v_pass, show="*", width=18)
        e.grid(row=2, column=3, columnspan=2, sticky="w", **pad)
        e.bind("<Return>", lambda _e: self._load_dbs())

        # Fichier
        f2 = ttk.LabelFrame(self, text="Fichier à importer (.sql, .sql.gz, .tar.gz)")
        f2.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        ttk.Entry(f2, textvariable=self.v_file, width=52).grid(row=0, column=0, **pad)
        ttk.Button(f2, text="Parcourir...", command=self._browse_file).grid(row=0, column=1, **pad)

        # Base cible
        f3 = ttk.LabelFrame(self, text="Base de destination")
        f3.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        ttk.Radiobutton(f3, text="Base existante :", variable=self.v_mode, value="existing",
                        command=self._mode_changed).grid(row=0, column=0, sticky="w", **pad)
        self.cb_db = ttk.Combobox(f3, textvariable=self.v_db, state="readonly", width=30)
        self.cb_db.grid(row=0, column=1, **pad)
        ttk.Button(f3, text="Charger les bases", command=self._load_dbs).grid(row=0, column=2, **pad)

        ttk.Radiobutton(f3, text="Nouvelle base :", variable=self.v_mode, value="new",
                        command=self._mode_changed).grid(row=1, column=0, sticky="w", **pad)
        self.en_new = ttk.Entry(f3, textvariable=self.v_newdb, width=33, state="disabled")
        self.en_new.grid(row=1, column=1, columnspan=2, sticky="w", **pad)

        # Options
        f4 = ttk.LabelFrame(self, text="Options")
        f4.grid(row=3, column=0, sticky="ew", padx=10, pady=4)
        ttk.Checkbutton(f4, text="--reconnect", variable=self.v_reconnect).grid(row=0, column=0, **pad)
        ttk.Checkbutton(f4, text="--force (continuer malgré les erreurs)", variable=self.v_force).grid(row=0, column=1, **pad)
        ttk.Label(f4, text="Charset :").grid(row=0, column=2, **pad)
        ttk.Combobox(f4, textvariable=self.v_charset, width=10,
                     values=["", "utf8", "utf8mb4", "latin1"]).grid(row=0, column=3, **pad)

        # Progression
        f5 = ttk.Frame(self)
        f5.grid(row=4, column=0, sticky="ew", padx=10, pady=(6, 2))
        self.pb = ttk.Progressbar(f5, length=480, maximum=100)
        self.pb.grid(row=0, column=0, sticky="ew")
        self.lbl_pct = ttk.Label(f5, text="0 %", width=7, anchor="e", font=("TkDefaultFont", 11, "bold"))
        self.lbl_pct.grid(row=0, column=1, padx=(6, 0))
        self.lbl_info = ttk.Label(f5, text="En attente", foreground="#555")
        self.lbl_info.grid(row=1, column=0, columnspan=2, sticky="w")

        # Journal
        self.txt = tk.Text(self, height=7, width=72, state="disabled", wrap="word")
        self.txt.grid(row=5, column=0, padx=10, pady=4)

        # Boutons
        f6 = ttk.Frame(self)
        f6.grid(row=6, column=0, sticky="e", padx=10, pady=(2, 10))
        self.btn_go = ttk.Button(f6, text="Importer", command=self._start)
        self.btn_go.grid(row=0, column=0, padx=4)
        self.btn_cancel = ttk.Button(f6, text="Annuler", command=self._cancel, state="disabled")
        self.btn_cancel.grid(row=0, column=1, padx=4)
        ttk.Button(f6, text="Quitter", command=self._quit).grid(row=0, column=2, padx=4)

        self.protocol("WM_DELETE_WINDOW", self._quit)

    # ------------------------------------------------------------ helpers UI
    def _log(self, msg):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _browse_mysql(self):
        p = filedialog.askopenfilename(title="Choisir le client mysql")
        if p:
            self.v_mysql.set(p)

    def _browse_file(self):
        p = filedialog.askopenfilename(
            title="Choisir le fichier",
            filetypes=[("Dumps SQL", "*.sql *.gz *.tgz *.tar.gz"), ("Tous", "*.*")])
        if p:
            self.v_file.set(p)

    def _mode_changed(self):
        new = self.v_mode.get() == "new"
        self.en_new.configure(state="normal" if new else "disabled")
        self.cb_db.configure(state="disabled" if new else "readonly")

    # ------------------------------------------------------------ MySQL
    def _base_cmd(self, db=None):
        cmd = [self.v_mysql.get().strip(), "-h", self.v_host.get().strip(),
               "-P", self.v_port.get().strip(), "-u", self.v_user.get().strip()]
        if self.v_reconnect.get():
            cmd.append("--reconnect")
        if self.v_force.get():
            cmd.append("--force")
        if self.v_charset.get().strip():
            cmd.append("--default-character-set=" + self.v_charset.get().strip())
        if db:
            cmd.append(db)
        return cmd

    def _env(self):
        env = os.environ.copy()
        # Le mot de passe passe par l'environnement : invisible dans la liste des processus
        env["MYSQL_PWD"] = self.v_pass.get()
        return env

    def _run_sql(self, sql):
        cmd = self._base_cmd()
        cmd += ["-N", "-B", "-e", sql]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run(cmd, env=self._env(), capture_output=True, text=True,
                           timeout=30, creationflags=flags)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "Erreur MySQL")
        return r.stdout

    def _load_dbs(self):
        try:
            out = self._run_sql("SHOW DATABASES")
        except FileNotFoundError:
            messagebox.showerror("Erreur", "Client mysql introuvable. Indiquez son chemin.")
            return
        except Exception as e:
            messagebox.showerror("Connexion impossible", str(e))
            return
        system = {"information_schema", "performance_schema", "mysql", "sys"}
        dbs = [d for d in out.split() if d not in system]
        self.cb_db["values"] = dbs
        if dbs and not self.v_db.get():
            self.v_db.set(dbs[0])
        self._log(f"{len(dbs)} base(s) trouvée(s).")

    # ------------------------------------------------------------ Import
    def _start(self):
        path = self.v_file.get().strip()
        if not os.path.isfile(path):
            messagebox.showwarning("Fichier", "Choisissez un fichier valide.")
            return

        if self.v_mode.get() == "new":
            db = self.v_newdb.get().strip()
            if not re.fullmatch(r"[A-Za-z0-9_$\-]{1,64}", db):
                messagebox.showwarning("Base", "Nom de base invalide (lettres, chiffres, _ $ - ).")
                return
            create = True
        else:
            db = self.v_db.get().strip()
            if not db:
                messagebox.showwarning("Base", "Choisissez une base (bouton « Charger les bases »).")
                return
            create = False
            if not messagebox.askyesno(
                    "Confirmation",
                    f"Importer dans la base existante « {db} » ?\n"
                    "Les tables de même nom seront écrasées si le dump contient DROP TABLE."):
                return

        self.cancel_evt.clear()
        self.running = True
        self.btn_go.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.pb["value"] = 0
        self.lbl_pct.configure(text="0 %")
        threading.Thread(target=self._worker, args=(path, db, create), daemon=True).start()

    def _cancel(self):
        self.cancel_evt.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass

    def _quit(self):
        if self.running and not messagebox.askyesno("Quitter", "Un import est en cours. L'arrêter et quitter ?"):
            return
        self._cancel()
        self.destroy()

    @staticmethod
    def _chunks(f):
        while True:
            b = f.read(CHUNK)
            if not b:
                return
            yield b

    def _source(self, path, raw):
        """Génère les blocs SQL ; la progression se base sur raw.tell() (octets compressés lus)."""
        low = path.lower()
        if low.endswith((".tar.gz", ".tgz")):
            found = False
            with tarfile.open(fileobj=raw, mode="r|gz") as tar:
                for m in tar:
                    if m.isfile() and m.name.lower().endswith(".sql"):
                        found = True
                        self.q.put(("log", f"Extraction de {m.name} ({fmt_size(m.size)})"))
                        ef = tar.extractfile(m)
                        yield from self._chunks(ef)
                        yield b"\n"
            if not found:
                raise RuntimeError("Aucun fichier .sql trouvé dans l'archive.")
        elif low.endswith(".gz"):
            with gzip.GzipFile(fileobj=raw) as g:
                yield from self._chunks(g)
        else:
            yield from self._chunks(raw)

    def _worker(self, path, db, create):
        stderr_lines = []
        try:
            total = os.path.getsize(path)
            if create:
                self._run_sql(f"CREATE DATABASE `{db}`")
                self.q.put(("log", f"Base « {db} » créée."))

            cmd = self._base_cmd(db)
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=self._env(),
                                         creationflags=flags)

            def read_err():
                for line in self.proc.stderr:
                    stderr_lines.append(line.decode(errors="replace").rstrip())
            t_err = threading.Thread(target=read_err, daemon=True)
            t_err.start()

            t0 = time.time()
            last = 0
            with open(path, "rb") as raw:
                for block in self._source(path, raw):
                    if self.cancel_evt.is_set():
                        raise InterruptedError()
                    try:
                        self.proc.stdin.write(block)
                    except (BrokenPipeError, OSError):
                        break  # mysql s'est arrêté (erreur SQL) : on lira stderr
                    now = time.time()
                    if now - last > 0.15:
                        last = now
                        done = raw.tell()
                        self.q.put(("progress", done, total, now - t0))
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            self.proc.wait()
            t_err.join(timeout=2)

            if self.cancel_evt.is_set():
                raise InterruptedError()
            if self.proc.returncode != 0:
                raise RuntimeError("\n".join(stderr_lines) or f"mysql a retourné le code {self.proc.returncode}")

            self.q.put(("progress", total, total, time.time() - t0))
            warn = ("\n" + "\n".join(stderr_lines)) if stderr_lines else ""
            self.q.put(("done", f"Import terminé en {fmt_time(time.time() - t0)}.{warn}"))
        except InterruptedError:
            self.q.put(("error", "Import annulé."))
        except Exception as e:
            self.q.put(("error", str(e)))

    # ------------------------------------------------------------ boucle UI
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, done, total, elapsed = msg
                    pct = min(100.0, done * 100.0 / total) if total else 0
                    self.pb["value"] = pct
                    self.lbl_pct.configure(text=f"{pct:.0f} %")
                    speed = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / speed if speed > 0 else 0
                    self.lbl_info.configure(
                        text=f"{fmt_size(done)} / {fmt_size(total)}  -  {fmt_size(speed)}/s  -  "
                             f"écoulé {fmt_time(elapsed)}  -  reste ~{fmt_time(eta)}")
                elif kind == "log":
                    self._log(msg[1])
                elif kind == "done":
                    self._finish()
                    self._log(msg[1])
                    messagebox.showinfo("Terminé", "Import terminé avec succès.")
                elif kind == "error":
                    self._finish()
                    self._log("ERREUR : " + msg[1])
                    messagebox.showerror("Erreur", msg[1][:1500])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self):
        self.running = False
        self.proc = None
        self.btn_go.configure(state="normal")
        self.btn_cancel.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
