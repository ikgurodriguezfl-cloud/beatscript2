"""
BeatScript IDE — Interfaz Gráfica Principal
============================================
Ventana principal del compilador BeatScript. Orquesta el pipeline completo:
Etapa 1 (Lexer) → Validación post-léxica → Etapa 2 (Parser) → MIDI → Audio.

Componentes visuales:
    Toolbar     → botones de acción (Compilar, Detener, Abrir, Guardar, Catálogo)
    Editor      → área de escritura de código BeatScript con resaltado de sintaxis
                  en tiempo real y números de línea sincronizados
    Token panel → tabla que muestra los tokens producidos por el lexer (Etapa 1)
    AST panel   → árbol sintáctico en texto producido por el parser (Etapa 2)
    Consola     → salida de mensajes del compilador (errores, estado, reproducci

Framework: customtkinter (tema oscuro) + tkinter.ttk (tablas Treeview)
Audio:      pygame.mixer para reproducir el archivo MIDI generado
"""

import ast
import tkinter as tk
from tkinter import ttk, filedialog
import customtkinter as ctk
import pygame
import os
import re
from beatscript.parser import BeatScriptParser, ast_to_tree_string, generate_visual_tree
from beatscript.semantic import SemanticAnalyzer


# Apariencia global
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


class BeatScriptIDE(ctk.CTk):
    """
    Ventana principal del IDE de BeatScript.

    Hereda de CTk (customtkinter) para obtener el tema oscuro automático.
    Construye la interfaz completa en __init__ y expone métodos privados
    (_build_*) para cada sección visual.

    Atributos relevantes:
        current_ast (Program | None): AST del último compilado sin errores.
                                      Necesario para generar el árbol PNG con Graphviz.
        editor (CTkTextbox):          Widget principal de escritura de código.
        token_tree (ttk.Treeview):    Tabla de tokens del lexer.
        ast_textbox (CTkTextbox):     Panel de texto del árbol AST.
        consola (CTkTextbox):         Salida de mensajes del compilador.
        status_label (CTkLabel):      Barra de estado con línea/columna.
        _line_canvas (tk.Canvas):     Canvas para los números de línea del editor.
    """

    def __init__(self):
        super().__init__()

        self.title("BeatScript IDE")
        self.geometry("1200x800")
        self.after(0, lambda: self.state("zoomed"))   # Maximizar al abrir

        # Inicializar pygame con parámetros de baja latencia para audio MIDI
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()

        # AST del último compilado exitoso; None hasta que se compile correctamente
        self.current_ast = None
        self.tac_routines = []
        self.tac_schedule = {}
        self._tab_spaces = 2

        self._build_toolbar()
        self._build_main_area()
        self._build_console()
        self._cargar_ejemplo()

    # ── Barra de herramientas superior ───────────────────────────────────────
    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=52, corner_radius=0)
        toolbar.pack(side="top", fill="x")
        toolbar.pack_propagate(False)

        ctk.CTkLabel(
            toolbar,
            text="BeatScript IDE",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left", padx=20)

        ctk.CTkButton(
            toolbar,
            text="Compilar y Reproducir",
            fg_color="#2e7d32",
            hover_color="#388e3c",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=210,
            command=self._compilar,
        ).pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Detener",
            fg_color="#b71c1c",
            hover_color="#c62828",
            font=ctk.CTkFont(size=13),
            width=120,
            command=self._detener,
        ).pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Abrir Archivo",
            fg_color="#1565c0",
            hover_color="#1976d2",
            font=ctk.CTkFont(size=13),
            width=150,
            command=self._abrir_archivo,
        ).pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Guardar Archivo",
            fg_color="#4a148c",
            hover_color="#6a1b9a",
            font=ctk.CTkFont(size=13),
            width=160,
            command=self._guardar_archivo,
        ).pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Catalogo de Errores",
            fg_color="#00695c",
            hover_color="#00796b",
            font=ctk.CTkFont(size=13),
            width=185,
            command=self._mostrar_documentacion_errores,
        ).pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkButton(
            toolbar,
            text="Cuadruplos y Tripletas",
            fg_color="#5d4037",
            hover_color="#6d4c41",
            font=ctk.CTkFont(size=13),
            width=200,
            command=self._mostrar_tac_visual,
        ).pack(side="left", padx=(0, 10), pady=10)

    # ── Área principal: editor + paneles derechos ────────────────────────────
    def _build_main_area(self):
        """
        Crea el contenedor principal dividido en dos columnas:
        - Columna 0 (weight=5): editor de código BeatScript
        - Columna 1 (weight=6): panel de tokens (arriba) + AST (abajo)
        """
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.pack(side="top", fill="both", expand=True, padx=8, pady=(8, 0))

        main.columnconfigure(0, weight=5)
        main.columnconfigure(1, weight=6)
        main.rowconfigure(0, weight=1)

        self._build_editor(main)
        self._build_right_panels(main)

    # ── Editor de código con números de línea y barra de estado ──────────────
    _EDITOR_BG  = "#1e1e1e"   # Fondo del editor (igual al tema oscuro del IDE)
    _LINENUM_FG = "#4a5568"   # Color de los números de línea

    def _build_editor(self, parent):
        """
        Construye el editor de código BeatScript con tres subcomponentes:
        1. Canvas izquierdo: números de línea dibujados con dlineinfo para
           alineación pixel-perfecta sin desfase al hacer scroll.
        2. CTkTextbox central: área de escritura principal con tags de color
           para el resaltado de sintaxis en tiempo real.
        3. CTkFrame inferior: barra de estado con posición del cursor.
        """
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        # pack: label arriba, status bar abajo, editor en el medio expandido
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(8, 2))
        header.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Editor de codigo",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#90caf9",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="+",
            width=34,
            height=26,
            fg_color="#1565c0",
            hover_color="#1976d2",
            command=self._nueva_pestana,
        ).grid(row=0, column=1, padx=(6, 0))

        ctk.CTkButton(
            header,
            text="x",
            width=34,
            height=26,
            fg_color="#37474f",
            hover_color="#455a64",
            command=self._cerrar_pestana_actual,
        ).grid(row=0, column=2, padx=(6, 0))

        # Barra de estado (pack al fondo antes del editor) 
        status_bar = ctk.CTkFrame(frame, height=26, corner_radius=0, fg_color="#1a1a2e")
        status_bar.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        status_bar.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            status_bar,
            text="  Línea: 1, Col: 1  |  Líneas totales: 1",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#78909c",
            anchor="w",
        )
        self.status_label.pack(side="left", padx=4, fill="x", expand=True)

        self.editor_tabs = ttk.Notebook(frame)
        self.editor_tabs.pack(fill="both", expand=True, padx=8, pady=(0, 0))
        self.editor_tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._tabs = {}
        self._untitled_count = 0
        self._nueva_pestana()

    def _configure_editor_tags(self, inner):
        inner.tag_configure("hl_keyword",    foreground="#7986cb")
        inner.tag_configure("hl_note",       foreground="#66bb6a")
        inner.tag_configure("hl_duration",   foreground="#ffb74d")
        inner.tag_configure("hl_instrument", foreground="#4dd0e1")
        inner.tag_configure("hl_number",     foreground="#ff8a65")
        inner.tag_configure("hl_brace",      foreground="#e0e0e0")
        inner.tag_configure("hl_comment",    foreground="#546e7a")
        inner.tag_configure("hl_identifier", foreground="#cfd8dc")

    def _nueva_pestana(self, title=None, content="", path=None):
        self._untitled_count += 1
        tab_title = title or f"Sin titulo {self._untitled_count}"
        tab = tk.Frame(self.editor_tabs, bg=self._EDITOR_BG, bd=0)
        editor_container = tk.Frame(tab, bg=self._EDITOR_BG, bd=0)
        editor_container.pack(fill="both", expand=True)

        line_canvas = tk.Canvas(
            editor_container,
            width=38,
            bg=self._EDITOR_BG,
            bd=0,
            highlightthickness=0,
            takefocus=False,
        )
        line_canvas.pack(side="left", fill="y")

        tk.Frame(editor_container, bg="#2a2a3e", width=1).pack(side="left", fill="y")

        editor = ctk.CTkTextbox(
            editor_container,
            font=("Consolas", 13),
            wrap="none",
            activate_scrollbars=True,
            fg_color=self._EDITOR_BG,
        )
        editor.pack(side="left", fill="both", expand=True)
        editor.insert("1.0", content)

        inner = editor._textbox
        inner.config(padx=6, pady=4, bd=0, highlightthickness=0, undo=True, autoseparators=True, maxundo=-1)
        self._configure_editor_tags(inner)
        self._bind_editor_shortcuts(inner)

        orig_yscroll = inner.cget("yscrollcommand")

        def _yscroll_chain(*args):
            if orig_yscroll:
                self.tk.call(orig_yscroll, *args)
            if self.editor is editor:
                self.after_idle(self._actualizar_lineas)

        inner.config(yscrollcommand=_yscroll_chain)
        line_canvas.bind(
            "<MouseWheel>",
            lambda e: inner.yview_scroll(int(-1 * (e.delta / 120)), "units")
        )

        inner.bind("<KeyRelease>",    self._actualizar_estado)
        inner.bind("<ButtonRelease>", self._actualizar_estado)
        inner.bind("<KeyRelease>",    self._on_key, add="+")
        inner.bind("<<Paste>>",       lambda e: self.after_idle(self._actualizar_lineas), add="+")
        inner.bind("<<Cut>>",         lambda e: self.after_idle(self._actualizar_lineas), add="+")
        inner.bind("<<Undo>>",        lambda e: self.after_idle(self._actualizar_lineas), add="+")
        inner.bind("<<Redo>>",        lambda e: self.after_idle(self._actualizar_lineas), add="+")
        inner.bind("<ButtonRelease>", lambda e: self.after_idle(self._actualizar_lineas), add="+")

        self.editor_tabs.add(tab, text=tab_title)
        self._tabs[str(tab)] = {"frame": tab, "editor": editor, "canvas": line_canvas, "path": path}
        self.editor_tabs.select(tab)
        self._set_active_tab(tab)
        self.after(100, self._actualizar_lineas)
        self.after(100, self._aplicar_resaltado)
        return tab

    def _bind_editor_shortcuts(self, inner):
        inner.bind("<Control-z>", self._on_undo, add="+")
        inner.bind("<Control-y>", self._on_redo, add="+")
        inner.bind("<Control-Z>", self._on_undo, add="+")
        inner.bind("<Control-Y>", self._on_redo, add="+")
        inner.bind("<Control-BackSpace>", self._on_ctrl_backspace, add="+")
        inner.bind("<Control-Delete>", self._on_ctrl_delete, add="+")
        inner.bind("<Tab>", self._on_tab, add="+")

    def _on_undo(self, event=None):
        try:
            self.editor._textbox.edit_undo()
            self.after_idle(self._actualizar_lineas)
            self.after_idle(self._actualizar_estado)
        except tk.TclError:
            pass
        return "break"

    def _on_redo(self, event=None):
        try:
            self.editor._textbox.edit_redo()
            self.after_idle(self._actualizar_lineas)
            self.after_idle(self._actualizar_estado)
        except tk.TclError:
            pass
        return "break"

    def _on_tab(self, event=None):
        widget = event.widget if event and getattr(event, "widget", None) else self.editor._textbox
        indent = " " * self._tab_spaces
        widget.insert("insert", indent)
        self.after_idle(self._actualizar_lineas)
        self.after_idle(self._actualizar_estado)
        return "break"

    def _delete_word_at_cursor(self, widget, direction="forward"):
        insert_index = widget.index("insert")
        line_end = widget.index(f"{insert_index} lineend")
        tail = widget.get(insert_index, line_end)

        if direction == "forward":
            match = re.search(r"\S+", tail)
            if not match:
                return False
            start = widget.index(f"{insert_index}+{match.start()}c")
            end = widget.index(f"{insert_index}+{match.end()}c")
        else:
            head = widget.get(f"{insert_index} linestart", insert_index)
            match = re.search(r"\S+\s*$", head)
            if not match:
                return False
            start = widget.index(f"{insert_index}-{len(head) - match.start()}c")
            end = insert_index

        widget.delete(start, end)
        return True

    def _on_ctrl_delete(self, event=None):
        widget = event.widget if event and getattr(event, "widget", None) else self.editor._textbox
        if self._delete_word_at_cursor(widget, direction="forward"):
            self.after_idle(self._actualizar_lineas)
            self.after_idle(self._actualizar_estado)
        return "break"

    def _on_ctrl_backspace(self, event=None):
        widget = event.widget if event and getattr(event, "widget", None) else self.editor._textbox
        if self._delete_word_at_cursor(widget, direction="backward"):
            self.after_idle(self._actualizar_lineas)
            self.after_idle(self._actualizar_estado)
        return "break"

    def _set_active_tab(self, tab_id):
        data = self._tabs.get(str(tab_id))
        if not data:
            return
        self.editor = data["editor"]
        self._line_canvas = data["canvas"]
        self.current_file = data.get("path")
        self._actualizar_estado()
        self.after_idle(self._actualizar_lineas)
        self.after_idle(self._aplicar_resaltado)

    def _on_tab_changed(self, event=None):
        selected = self.editor_tabs.select()
        if selected:
            self._set_active_tab(selected)

    def _cerrar_pestana_actual(self):
        selected = self.editor_tabs.select()
        if not selected or len(self.editor_tabs.tabs()) <= 1:
            return
        self.editor_tabs.forget(selected)
        self._tabs.pop(str(selected), None)
        next_tab = self.editor_tabs.select()
        if next_tab:
            self._set_active_tab(next_tab)

    def _documentos_abiertos(self):
        docs = []
        for tab_id in self.editor_tabs.tabs():
            data = self._tabs.get(str(tab_id))
            if not data:
                continue
            source = data["editor"].get("1.0", "end-1c").strip()
            if source:
                docs.append((tab_id, self.editor_tabs.tab(tab_id, "text"), source))
        return docs

    #  Panel derecho: tabla de tokens (50%) + árbol AST (50%) 
    def _build_right_panels(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        frame.grid(row=0, column=1, sticky="nsew")

        # Dos filas de igual peso → 50 % / 50 %
        frame.rowconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        self._build_token_panel(frame)  # Fila 0 — tabla léxica
        self._build_ast_panel(frame)    # Fila 1 — árbol sintáctico

    #  Panel de tokens (mitad superior del área derecha) 
    def _build_token_panel(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text="Tabla de Tokens — Lexer (Etapa 1)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a5d6a7",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 4))

        # Contenedor para Treeview + scrollbars (ttk no tiene corner_radius)
        container = tk.Frame(frame, bg="#1e1e1e")
        container.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        #  Estilo oscuro para el Treeview (ttk no hereda el tema de ctk) 
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Token.Treeview",
            background="#1e1e1e",
            foreground="#e0e0e0",
            fieldbackground="#1e1e1e",
            rowheight=22,
            font=("Consolas", 10),
            borderwidth=0,
        )
        style.configure(
            "Token.Treeview.Heading",
            background="#2d2d2d",
            foreground="#90caf9",
            font=("Consolas", 10, "bold"),
            relief="flat",
        )
        style.map(
            "Token.Treeview",
            background=[("selected", "#1565c0")],
            foreground=[("selected", "#ffffff")],
        )

        #  Treeview con columnas: #, TIPO, VALOR, LÍNEA, COL 
        self.token_tree = ttk.Treeview(
            container,
            columns=("num", "tipo", "valor", "linea", "col"),
            show="headings",   # Ocultar la columna árbol por defecto
            style="Token.Treeview",
            selectmode="browse",
        )

        # Encabezados
        self.token_tree.heading("num",   text="#")
        self.token_tree.heading("tipo",  text="TIPO")
        self.token_tree.heading("valor", text="VALOR")
        self.token_tree.heading("linea", text="LÍNEA")
        self.token_tree.heading("col",   text="COL")

        # Anchos de columna
        self.token_tree.column("num",   width=40,  anchor="center", stretch=False)
        self.token_tree.column("tipo",  width=150, anchor="w")
        self.token_tree.column("valor", width=140, anchor="w")
        self.token_tree.column("linea", width=58,  anchor="center", stretch=False)
        self.token_tree.column("col",   width=50,  anchor="center", stretch=False)

        # Colores alternos para las filas (efecto zebra)
        self.token_tree.tag_configure("par",   background="#252525")
        self.token_tree.tag_configure("impar", background="#1e1e1e")

        # Scrollbars sincronizadas
        v_scroll = ttk.Scrollbar(container, orient="vertical",   command=self.token_tree.yview)
        h_scroll = ttk.Scrollbar(container, orient="horizontal", command=self.token_tree.xview)
        self.token_tree.configure(
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
        )

        self.token_tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

    #  Panel AST (mitad inferior del área derecha) 
    def _build_ast_panel(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        #  Fila de encabezado: etiqueta + botón de árbol gráfico 
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header.columnconfigure(0, weight=1)  # La etiqueta se expande

        self.ast_label = ctk.CTkLabel(
            header,
            text="Árbol Sintáctico — Parser (Etapa 2)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffcc80",
        )
        self.ast_label.grid(row=0, column=0, sticky="w")

        # Botón que abre el árbol de derivación visual (PNG via Graphviz)
        ctk.CTkButton(
            header,
            text="Ver Arbol de Derivacion",
            fg_color="#4527a0",
            hover_color="#512da8",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=210,
            height=28,
            command=self._abrir_arbol_visual,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.ast_textbox = ctk.CTkTextbox(
            frame,
            font=("Consolas", 11),
            wrap="none",
            activate_scrollbars=True,
            text_color="#a1d995",
            fg_color="#1a1a1a",
        )
        self.ast_textbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.ast_textbox.insert("1.0", "— El AST se generará aquí (Etapa 2) —")
        self.ast_textbox.configure(state="disabled")

    #  Consola inferior 
    def _build_console(self):
        frame = ctk.CTkFrame(self, height=145, corner_radius=8)
        frame.pack(side="bottom", fill="x", padx=8, pady=8)
        frame.pack_propagate(False)

        ctk.CTkLabel(
            frame,
            text="Consola",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ef9a9a",
        ).pack(anchor="w", padx=12, pady=(6, 2))

        self.consola = ctk.CTkTextbox(
            frame,
            font=("Consolas", 12),
            state="disabled",
            text_color="#e0e0e0",
            fg_color="#1a1a1a",
        )
        self.consola.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    #  Números de línea (canvas) 
    def _actualizar_lineas(self):
        """
        Redibuja los números de línea en el canvas usando dlineinfo.
        Calcula el offset vertical entre el canvas y el _textbox interno
        para compensar el padding interno del CTkTextbox.
        """
        try:
            inner  = self.editor._textbox
            canvas = self._line_canvas
            canvas.delete("all")

            # Offset Y: diferencia entre el origen del canvas y el del _textbox
            # (el CTkTextbox añade padding interno que desplaza el _textbox)
            offset = inner.winfo_rooty() - canvas.winfo_rooty()

            first = int(inner.index("@0,0").split(".")[0])
            last  = int(inner.index(f"@0,{inner.winfo_height()}").split(".")[0])
            cw    = canvas.winfo_width() - 4

            for lineno in range(first, last + 2):
                info = inner.dlineinfo(f"{lineno}.0")
                if info is None:
                    break
                # info[1]=y_top, info[3]=height — aplicar offset del widget
                y_center = info[1] + info[3] // 2 + offset
                canvas.create_text(
                    cw, y_center,
                    text=str(lineno),
                    anchor="e",
                    fill=self._LINENUM_FG,
                    font=("Consolas", 13),
                )
        except Exception:
            pass

    def _on_editor_scroll(self, *args):
        """No se usa con el canvas — el chain en yscrollcommand llama a _actualizar_lineas."""
        pass

    # ── Resaltado de sintaxis en tiempo real ─────────────────────────────────
    # Mapeo de tipo de token → tag de color definido en _build_editor().
    # Cada tag tiene un color asignado con inner.tag_configure().
    _TOKEN_TAG = {
        "TEMPO_KW":      "hl_keyword",
        "INSTRUMENT_KW": "hl_keyword",
        "TRACK_KW":      "hl_keyword",
        "REPEAT_KW":     "hl_keyword",
        "CHORD_KW":      "hl_keyword",
        "REST":          "hl_keyword",
        "VOLUME_KW":     "hl_keyword",
        "PAN_KW":        "hl_keyword",
        "TRANSPOSE_KW":  "hl_keyword",
        "COMPAS_KW":     "hl_keyword",
        "ACCENT_KW":     "hl_keyword",
        "SEQUENCE_KW":   "hl_keyword",
        "NOTE":          "hl_note",
        "DURATION":      "hl_duration",
        "INSTR_NAME":    "hl_instrument",
        "NUMBER":        "hl_number",
        "LBRACE":        "hl_brace",
        "RBRACE":        "hl_brace",
        "LPAREN":        "hl_brace",
        "RPAREN":        "hl_brace",
        "COMMA":         "hl_brace",
        "IDENTIFIER":    "hl_identifier",
    }

    def _on_key(self, event=None):
        """
        Handler de KeyRelease: dispara el resaltado y actualiza los números
        de línea cada vez que el usuario escribe o modifica el código.
        Usa after_idle para las líneas para no bloquear la respuesta del teclado.
        """
        self._aplicar_resaltado()
        self.after_idle(self._actualizar_lineas)

    def _aplicar_resaltado(self):
        """
        Aplica resaltado de sintaxis en tiempo real al editor.

        Funciona en dos pasos:
        1. Colorea comentarios con regex directa (re.finditer) porque el lexer
           los descarta y no los incluye en la lista de tokens.
        2. Llama al lexer formal (tokenize) para obtener los tokens reales,
           y aplica el tag de color correspondiente a cada uno usando tok.lexpos
           como índice absoluto de posición en el texto.

        Silencia cualquier excepción para no interrumpir la escritura del usuario
        cuando el código está incompleto (ej: bloque sin cerrar).
        """
        import re
        try:
            from beatscript.lexer import tokenize
        except ImportError:
            return

        inner  = self.editor._textbox
        source = inner.get("1.0", "end-1c")

        # Limpiar todos los tags anteriores antes de redibujar
        for tag in self._TOKEN_TAG.values():
            inner.tag_remove(tag, "1.0", "end")
        inner.tag_remove("hl_comment", "1.0", "end")

        # Paso 1: colorear comentarios con regex (el lexer los descarta)
        for m in re.finditer(r"##[^\n]*", source):
            start = f"1.0 + {m.start()} chars"
            end   = f"1.0 + {m.end()} chars"
            inner.tag_add("hl_comment", start, end)

        # Paso 2: colorear tokens devueltos por el lexer formal
        try:
            tokens, _ = tokenize(source, collect_errors=True)
        except Exception:
            return

        for tok in tokens:
            tag = self._TOKEN_TAG.get(tok.type)
            if tag is None:
                continue
            tok_len = len(str(tok.value))
            start   = f"1.0 + {tok.lexpos} chars"
            end     = f"1.0 + {tok.lexpos + tok_len} chars"
            inner.tag_add(tag, start, end)

    #  Barra de estado: actualizar posición del cursor 
    def _actualizar_estado(self, event=None):
        """
        Actualiza la barra de estado inferior del editor con la posición
        actual del cursor y el total de líneas del documento.
        """
        try:
            inner = self.editor._textbox
            # "linea.columna" — las columnas empiezan en 0 en tk.Text
            pos = inner.index("insert")
            linea, col_raw = pos.split(".")
            col = int(col_raw) + 1  # Convertir a base 1

            total = int(inner.index("end-1c").split(".")[0])
            # Descontar línea vacía final si el texto termina en newline
            if inner.get(f"{total}.0", f"{total}.end").strip() == "":
                total = max(1, total - 1)

            self.status_label.configure(
                text=f"  Línea: {linea}, Col: {col}  |  Líneas totales: {total}"
            )
        except Exception:
            pass

    def _mostrar_ast(self, ast):
        """
        Muestra el AST en el panel de texto derecho usando ast_to_tree_string().
        Solo se llama cuando la compilación es exitosa (sin errores).
        Actualiza la etiqueta del panel con el conteo de nodos del árbol.
        """
        self.ast_textbox.configure(state="normal")
        self.ast_textbox.delete("1.0", "end")

        try:
            tree_str = ast_to_tree_string(ast)
        except Exception as e:
            tree_str = f"[No se pudo generar la vista del AST: {e}]"
            self._log(f"  Advertencia: fallo al renderizar el AST — {e}")

        self.ast_textbox.insert("1.0", tree_str)
        self.ast_textbox.configure(state="disabled")
        num_nodes = tree_str.count("\n") + 1
        self.ast_label.configure(text=f"Árbol Sintáctico — Parser (Etapa 2 — {num_nodes} nodos)")

    #  Abrir árbol de derivación visual (Graphviz → PNG) 
    def _abrir_arbol_visual(self):
        """
        Genera el árbol de derivación en PNG usando Graphviz y lo abre
        automáticamente con el visor de imágenes predeterminado de Windows.

        Requiere:
          1. pip install graphviz
          2. Instalar el binario Graphviz desde https://graphviz.org/download/
             y añadirlo al PATH del sistema.
        """
        if self.current_ast is None:
            self._log(
                "  Primero compila el código correctamente para "
                "generar el árbol de derivación."
            )
            return

        self._log("Generando árbol de derivación visual...")
        try:
            ruta = generate_visual_tree(self.current_ast, output_filename="parse_tree")
            self._log(f"  Árbol generado: {ruta}")
            # os.startfile abre la imagen con el visor predeterminado del sistema
            os.startfile(ruta)
        except ImportError:
            self._log("  Error: el paquete Python 'graphviz' no está instalado.")
            self._log("  Solución: pip install graphviz")
        except Exception as e:
            self._log(f"  Error al generar el árbol: {e}")
            if any(k in str(e).lower() for k in ("not found", "dot", "executable")):
                self._log(
                    "  Graphviz no está en el PATH. Instálalo desde "
                    "https://graphviz.org/download/ y marca 'Add to PATH'."
                )

    def _compilar(self):
        self._log("", clear=True)

        documentos = self._documentos_abiertos()
        if not documentos:
            self._log("No hay pestañas con codigo BeatScript para compilar.")
            return

        tokens_por_documento = []
        total_errores = []
        ast_activo = None
        tokens_activos = []
        source_activo = ""
        selected_tab = self.editor_tabs.select()
        selected_id = selected_tab

        for tab_id, nombre, source in documentos:
            self._log(f"[{nombre}] Iniciando analisis lexico...")
            try:
                from beatscript.lexer import tokenize
                tokens, errores_lexicos = tokenize(source, collect_errors=True)
            except ImportError:
                self._log("beatscript.lexer no encontrado - usando datos de prueba")
                tokens, errores_lexicos = self._mock_tokens(), []
            except Exception as e:
                self._log(f"Error durante el analisis lexico: {e}")
                return

            self._log(f"  Analisis lexico completado - {len(tokens)} tokens encontrados.")
            avisos_validacion = self._validar_tokens_extra(tokens, source)

            self._log(f"[{nombre}] Iniciando analisis sintactico...")
            try:
                parser = BeatScriptParser(tokens, source)
                ast = parser.parse()
                errores_sintacticos = parser.errors
            except Exception as e:
                self._log(f"Error durante el analisis sintactico: {e}")
                return

            self._log("  Analisis sintactico completado.")

            # ── ETAPA 3: ANÁLISIS SEMÁNTICO ──────────────────────────────────
            self._log(f"[{nombre}] Iniciando analisis semantico...")
            try:
                analyzer = SemanticAnalyzer(ast)
                errores_semanticos, advertencias_semanticas = analyzer.analyze()
            except Exception as e:
                self._log(f"  Error durante el analisis semantico: {e}")
                total_errores.append(f"[{nombre}] Fallo interno del analizador semántico: {e}")
                errores_semanticos, advertencias_semanticas = [], []
            else:
                self._log(
                    f"  Analisis semantico completado — "
                    f"{len(errores_semanticos)} error(es), "
                    f"{len(advertencias_semanticas)} advertencia(s)."
                )

            # Advertencias: se muestran pero NO detienen la compilación
            for adv in advertencias_semanticas:
                self._log(f"  [{nombre}] {adv}")

            for err in errores_lexicos:
                total_errores.append(f"[{nombre}] {err['msg']}")
            for av in avisos_validacion:
                total_errores.append(f"[{nombre}] {av}")
            for err in errores_sintacticos:
                total_errores.append(f"[{nombre}] {err}")
            # Errores semánticos sí detienen la compilación
            for err in errores_semanticos:
                total_errores.append(f"[{nombre}] {err}")

            tokens_por_documento.append(tokens)
            if tab_id == selected_id:
                ast_activo = ast
                tokens_activos = tokens
                source_activo = source

        if not tokens_activos and tokens_por_documento:
            tokens_activos = tokens_por_documento[0]
            source_activo = documentos[0][2]

        self._llenar_tabla_tokens(tokens_activos, source_activo)

        if total_errores:
            for msg in total_errores:
                self._log(f"  {msg}")
            self._log(f"\nCompilacion detenida - {len(total_errores)} error(es) en total encontrados.")
            return

        self.current_ast = ast_activo
        if ast_activo is not None:
            self._mostrar_ast(ast_activo)

            from beatscript.tac_gen import TACGenerator

            prologue, routines, schedule = TACGenerator(ast_activo).generate()
            self.tac_routines = routines
            self.tac_schedule = schedule
            self._log(f"  Código de tres direcciones generado — {len(routines)} rutina(s).")

        try:
            from beatscript.midi_gen import tokens_to_midi_documents
            midi_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "output.mid"
            )
            tokens_to_midi_documents(tokens_por_documento, midi_path)
            pygame.mixer.music.load(midi_path)
            pygame.mixer.music.play()
            self._log(f" Reproduciendo output.mid con {len(documentos)} pestaña(s)...")
        except Exception as e:
            self._log(f"  No se pudo reproducir el MIDI: {e}")

    # Poblar la tabla de tokens del panel derecho 
    def _llenar_tabla_tokens(self, tokens: list, source: str):
        """
        Limpia la tabla de tokens y la rellena con los resultados del lexer.
        Aplica filas alternas (par/impar) para facilitar la lectura.
        """
        # Limpiar filas previas
        for item in self.token_tree.get_children():
            self.token_tree.delete(item)

        for i, tok in enumerate(tokens, 1):
            col = self._calcular_columna(source, tok)
            tag = "par" if i % 2 == 0 else "impar"
            self.token_tree.insert(
                "",
                "end",
                values=(i, tok.type, str(tok.value), tok.lineno, col),
                tags=(tag,),
            )

    def _validar_tokens_extra(self, tokens: list, source: str) -> list:
        """
        Validación post-léxica: detecta patrones inválidos que el lexer acepta
        sintácticamente pero que representan errores semánticos o de uso.

        Se ejecuta entre la Etapa 1 (Lexer) y la Etapa 2 (Parser), recorriendo
        la lista de tokens y verificando combinaciones problemáticas de tokens
        consecutivos. No modifica los tokens; solo acumula mensajes de error.

        Patrones que detecta:
            - instrument IDENTIFIER   → instrumento no reconocido en BeatScript
            - tempo no-NUMBER         → tempo seguido de algo que no es número
            - volume no-NUMBER        → volume con valor no numérico
            - volume NUMBER fuera     → volumen fuera del rango MIDI (0-127)
            - NOTE/REST seguido de NUMBER → nota con octava de más de un dígito (ej: E44)
            - NOTE/REST seguido de IDENTIFIER → duración inválida (ej: negraa)
            - IDENTIFIER con forma de nota → nota mal formada (ej: C4x, D##3)

        Args:
            tokens: Lista de LexToken producida por el lexer.
            source: Código fuente original para calcular columnas.

        Returns:
            Lista de strings con mensajes de error [ERROR LÉXICO] formateados.
            Lista vacía si no se detectaron problemas.
        """
        import re
        avisos = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]

            if tok.type == "INSTRUMENT_KW":
                siguiente = tokens[i + 1] if i + 1 < len(tokens) else None
                if siguiente and siguiente.type == "IDENTIFIER":
                    col = self._calcular_columna(source, siguiente)
                    avisos.append(
                        f"[ERROR LÉXICO] Línea {siguiente.lineno}, Col {col}: "
                        f"'{siguiente.value}' no es un instrumento reconocido. "
                        f"Usa: piano, guitar, violin, flute, drums, bass, trumpet..."
                    )

            elif tok.type == "TEMPO_KW":
                siguiente = tokens[i + 1] if i + 1 < len(tokens) else None
                if siguiente and siguiente.type != "NUMBER":
                    col = self._calcular_columna(source, siguiente)
                    avisos.append(
                        f"[ERROR LÉXICO] Línea {siguiente.lineno}, Col {col}: "
                        f"se esperaba un número después de 'tempo', "
                        f"se encontró '{siguiente.value}'"
                    )

            elif tok.type == "VOLUME_KW":
                siguiente = tokens[i + 1] if i + 1 < len(tokens) else None

            elif tok.type == "PAN_KW":
                siguiente = tokens[i + 1] if i + 1 < len(tokens) else None

            elif tok.type in ("NOTE", "REST"):
                siguiente = tokens[i + 1] if i + 1 < len(tokens) else None
                if siguiente and siguiente.type == "NUMBER":
                    col = self._calcular_columna(source, tok)
                    avisos.append(
                        f"[ERROR LÉXICO] Línea {tok.lineno}, Col {col}: "
                        f"'{tok.value}{siguiente.value}' parece una nota inválida — "
                        f"el número de octava debe ser un solo dígito: ej: E4, C4, D#3"
                    )
                elif siguiente and siguiente.type == "IDENTIFIER":
                    col = self._calcular_columna(source, siguiente)
                    avisos.append(
                        f"[ERROR LÉXICO] Línea {siguiente.lineno}, Col {col}: "
                        f"'{siguiente.value}' no es una duración válida — usa: "
                        f"negra, blanca, corchea, redonda, semicorchea, fusa, semifusa o *_punto"
                    )

            elif tok.type == "IDENTIFIER":
                val = tok.value
                anterior = tokens[i - 1] if i > 0 else None
                # Detecta posibles notas mal formadas (ej. "C4x", "D##3")
                parece_nota = re.match(r"^[A-Ga-g](?:[#b]{0,2}\d+[A-Za-z0-9#b]*|[#b]{2,}\d*)$", val)
                if parece_nota and not (anterior and anterior.type == "TRACK_KW"):
                    col = self._calcular_columna(source, tok)
                    avisos.append(
                        f"[ERROR LÉXICO] Línea {tok.lineno}, Col {col}: "
                        f"'{val}' parece una nota inválida — "
                        f"formato: [A-G][#b]?[octava], ej: C4, D#3, Eb5"
                    )

            i += 1
        return avisos

    def _abrir_archivo(self):
        """
        Abre un diálogo de selección de archivo y carga su contenido en el editor.
        Acepta archivos .bs (BeatScript), .txt y cualquier otro formato.
        Actualiza el título de la ventana con el nombre del archivo cargado.
        """
        ruta = filedialog.askopenfilename(
            title="Abrir archivo BeatScript",
            filetypes=[
                ("Archivos BeatScript", "*.bs"),
                ("Archivos de texto",   "*.txt"),
                ("Todos los archivos",  "*.*"),
            ],
        )
        if not ruta:
            return  # El usuario canceló

        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
            self._nueva_pestana(os.path.basename(ruta), contenido, ruta)
            self.title(f"BeatScript IDE - {os.path.basename(ruta)}")
            self._log(f"Archivo abierto: {ruta}")
        except Exception as e:
            self._log(f"Error al abrir el archivo: {e}")

    def _guardar_archivo(self):
        """
        Abre un diálogo de guardado y escribe el contenido del editor en disco.
        La extensión por defecto es .bs (BeatScript). Actualiza el título de
        la ventana con el nombre del archivo guardado.
        """
        ruta = filedialog.asksaveasfilename(
            title="Guardar archivo BeatScript",
            defaultextension=".bs",
            filetypes=[
                ("Archivos BeatScript", "*.bs"),
                ("Archivos de texto",   "*.txt"),
                ("Todos los archivos",  "*.*"),
            ],
        )
        if not ruta:
            return  # El usuario canceló

        try:
            contenido = self.editor.get("1.0", "end-1c")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(contenido)
            selected = self.editor_tabs.select()
            if selected:
                self.editor_tabs.tab(selected, text=os.path.basename(ruta))
                if str(selected) in self._tabs:
                    self._tabs[str(selected)]["path"] = ruta
            self.title(f"BeatScript IDE - {os.path.basename(ruta)}")
            self._log(f"Archivo guardado: {ruta}")
        except Exception as e:
            self._log(f"Error al guardar el archivo: {e}")

    def _mostrar_documentacion_errores(self):
        """
        Abre una ventana modal con el catálogo completo de errores de BeatScript.

        La ventana contiene tarjetas organizadas en 3 secciones:
            1. Errores de validación lógica  (ERR-VAL): patrones post-léxicos
            2. Errores léxicos               (ERR-LEX): caracteres inválidos
            3. Errores sintácticos           (ERR-SIN): violaciones gramaticales

        Cada tarjeta muestra: código del error, título, causa y resolución.
        Se centra automáticamente sobre la ventana principal.
        """

        ventana = ctk.CTkToplevel(self)
        ventana.title("Catalogo de Errores - BeatScript")
        ventana.geometry("720x600")
        ventana.resizable(True, True)
        ventana.grab_set()

        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - 720) // 2
        y = self.winfo_y() + (self.winfo_height() - 600) // 2
        ventana.geometry(f"720x600+{x}+{y}")

        # ── Titulo principal ──────────────────────────────────────────────────
        ctk.CTkLabel(
            ventana,
            text="Documentacion de Errores - BeatScript v1.0",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#90caf9",
        ).pack(anchor="w", padx=24, pady=(18, 2))

        ctk.CTkLabel(
            ventana,
            text="Clasificacion: Validacion  |  Lexico  |  Sintactico",
            font=ctk.CTkFont(size=11),
            text_color="#546e7a",
        ).pack(anchor="w", padx=24, pady=(0, 12))

        # ── Area scrollable con tarjetas ──────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(ventana, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # ── Helpers ───────────────────────────────────────────────────────────
        def seccion(texto):
            ctk.CTkLabel(
                scroll,
                text=texto,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#80cbc4",
                anchor="w",
            ).pack(fill="x", padx=4, pady=(14, 4))

        def tarjeta(codigo, titulo, causa, resolucion):
            card = ctk.CTkFrame(scroll, corner_radius=10, fg_color="#1e2a2a")
            card.pack(fill="x", padx=4, pady=5)

            # Codigo + Titulo
            ctk.CTkLabel(
                card,
                text=f"{codigo}  {titulo}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#e0e0e0",
                anchor="w",
            ).pack(anchor="w", padx=14, pady=(10, 4))

            sep = ctk.CTkFrame(card, height=1, fg_color="#2e3e3e")
            sep.pack(fill="x", padx=14, pady=(0, 6))

            # Causa
            fila_c = ctk.CTkFrame(card, fg_color="transparent")
            fila_c.pack(fill="x", padx=14, pady=(0, 2))
            ctk.CTkLabel(
                fila_c,
                text="Causa",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#ef9a9a",
                width=80,
                anchor="w",
            ).pack(side="left", anchor="n")
            ctk.CTkLabel(
                fila_c,
                text=causa,
                font=ctk.CTkFont(size=11),
                text_color="#b0bec5",
                wraplength=520,
                justify="left",
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

            # Resolucion
            fila_r = ctk.CTkFrame(card, fg_color="transparent")
            fila_r.pack(fill="x", padx=14, pady=(2, 10))
            ctk.CTkLabel(
                fila_r,
                text="Resolucion",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#a5d6a7",
                width=80,
                anchor="w",
            ).pack(side="left", anchor="n")
            ctk.CTkLabel(
                fila_r,
                text=resolucion,
                font=ctk.CTkFont(size=11),
                text_color="#b0bec5",
                wraplength=520,
                justify="left",
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

        # ── Seccion 1: Validacion ─────────────────────────────────────────────
        seccion("1. Errores de Validacion Logica  (Warnings)")

        tarjeta(
            "ERR-VAL-01", "Token de Identificador Corrupto",
            causa="El lexer genero un identificador que inicia con una letra valida de nota (A-G) pero contiene sufijos invalidos. Ej: E44, Er21",
            resolucion="Verificar la sintaxis de la nota. El formato estricto es [A-G][#b]?[0-9]",
        )
        tarjeta(
            "ERR-VAL-02", "Tipo de Dato Duracion Desconocido",
            causa="Se esperaba un valor de la enumeracion de duraciones (negra, blanca, etc.) pero se recibio un string no reconocido. Ej: blancaa, negra1",
            resolucion="Usar: negra | blanca | corchea | redonda | semicorchea | fusa | semifusa, o agregar _punto",
        )

        # ── Seccion 2: Lexico ─────────────────────────────────────────────────
        seccion("2. Errores Lexicos  (Lexical Errors)")

        tarjeta(
            "ERR-LEX-01", "Caracter Ilegal Detectado",
            causa="El automata finito detecto un simbolo que no pertenece al alfabeto de BeatScript. Ej: @tempo, dollar-track, C4!",
            resolucion="Eliminar el caracter no valido. El analizador lo saltara automaticamente pero marcara el error en consola.",
        )

        # ── Seccion 3: Sintactico ─────────────────────────────────────────────
        seccion("3. Errores Sintacticos  (Parsing Errors)")

        tarjeta(
            "ERR-SIN-01", "Violacion de Estructura de Evento",
            causa="Un bloque (track) contiene una secuencia de tokens que no forma un evento musical valido. Ej: NUMBER en lugar de DURATION tras una nota.",
            resolucion="Asegurar que cada instruccion cumpla la regla de produccion: evento -> NOTE DURATION",
        )
        tarjeta(
            "ERR-SIN-02", "EOF Inesperado / Bloque No Cerrado",
            causa="El compilador llego al final del archivo y el stack del parser detecto que falta un delimitador }.",
            resolucion="Cerrar todos los bloques track y repeat que fueron abiertos con {.",
        )
        tarjeta(
            "ERR-SIN-03", "Comando Global No Reconocido",
            causa="Fuera de los bloques se uso una palabra clave no definida como declaracion principal. Ej: trackk en lugar de track.",
            resolucion="El compilador entrara en Modo Panico y descartara tokens hasta encontrar una palabra reservada valida. Corregir la palabra clave.",
        )

        ctk.CTkButton(
            ventana,
            text="Cerrar",
            fg_color="#37474f",
            hover_color="#455a64",
            width=110,
            command=ventana.destroy,
        ).pack(pady=(0, 12))

    def _mostrar_tac_visual(self):
        if not self.tac_routines:
            self._log(
                "  Primero compila el código correctamente para "
                "generar el código de tres direcciones."
            )
            return

        from beatscript.tac_gen import (
            quads_to_triples,
            quads_to_table_rows,
            triples_to_table_rows,
        )

        ventana = ctk.CTkToplevel(self)
        ventana.title("Codigo de Tres Direcciones - BeatScript")
        ventana.geometry("800x600")
        ventana.resizable(True, True)

        # transient() + grab_set() retrasado evita el "zoom" de la ventana
        # principal al abrir el modal (glitch conocido de CTkToplevel).
        ventana.transient(self)

        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 800) // 2
        y = self.winfo_y() + (self.winfo_height() - 600) // 2
        ventana.geometry(f"800x600+{x}+{y}")
        ventana.after(50, ventana.grab_set)

        header = ctk.CTkFrame(ventana, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(18, 4))
        header.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Codigo de Tres Direcciones",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#90caf9",
        ).grid(row=0, column=0, sticky="w")

        # ── Selector de rutina ─────────────────────────────────────────────
        selector_frame = ctk.CTkFrame(ventana, fg_color="transparent")
        selector_frame.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkLabel(
            selector_frame, text="Rutina:", font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=(0, 8))

        nombres_rutinas = [r.name for r in self.tac_routines]
        rutina_var = tk.StringVar(value=nombres_rutinas[0])
        rutina_menu = ctk.CTkOptionMenu(
            selector_frame,
            values=nombres_rutinas,
            variable=rutina_var,
            command=lambda _=None: _refrescar_tablas(),
            width=220,
        )
        rutina_menu.pack(side="left")

        # ── Pestañas tipo hoja de Excel: Cuadruplos | Tripletas ─────────────
        # Reutiliza el estilo "Token.Treeview" ya configurado en
        # _build_token_panel — NO se vuelve a llamar theme_use() aquí.
        tabs = ttk.Notebook(ventana)
        tabs.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        tab_quad = tk.Frame(tabs, bg="#1e1e1e")
        tab_triple = tk.Frame(tabs, bg="#1e1e1e")
        tabs.add(tab_quad, text="  Cuadruplos  ")
        tabs.add(tab_triple, text="  Tripletas  ")

        def _crear_tabla(parent, columnas, encabezados, anchos):
            cont = tk.Frame(parent, bg="#1e1e1e")
            cont.pack(fill="both", expand=True, padx=8, pady=8)
            cont.rowconfigure(0, weight=1)
            cont.columnconfigure(0, weight=1)

            tree = ttk.Treeview(
                cont, columns=columnas, show="headings",
                style="Token.Treeview", selectmode="browse",
            )
            for c, h, w in zip(columnas, encabezados, anchos):
                tree.heading(c, text=h)
                tree.column(c, width=w, anchor="center" if c == "num" else "w",
                            stretch=(c != "num"))
            tree.tag_configure("par", background="#252525")
            tree.tag_configure("impar", background="#1e1e1e")

            v = ttk.Scrollbar(cont, orient="vertical", command=tree.yview)
            h_ = ttk.Scrollbar(cont, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=v.set, xscrollcommand=h_.set)
            tree.grid(row=0, column=0, sticky="nsew")
            v.grid(row=0, column=1, sticky="ns")
            h_.grid(row=1, column=0, sticky="ew")
            return tree

        tac_tree_quad = _crear_tabla(
            tab_quad,
            ("num", "op", "arg1", "arg2", "result"),
            ("#", "OP", "ARG1", "ARG2", "RESULTADO"),
            (50, 110, 150, 150, 150),
        )
        tac_tree_triple = _crear_tabla(
            tab_triple,
            ("num", "op", "arg1", "arg2"),
            ("(#)", "OP", "ARG1", "ARG2"),
            (60, 110, 180, 180),
        )

        def _rutina_actual():
            nombre = rutina_var.get()
            return next(
                (r for r in self.tac_routines if r.name == nombre),
                self.tac_routines[0],
            )

        def _refrescar_tablas():
            rutina = _rutina_actual()

            for item in tac_tree_quad.get_children():
                tac_tree_quad.delete(item)
            for i, fila in enumerate(quads_to_table_rows(rutina.quads)):
                tag = "par" if i % 2 == 0 else "impar"
                tac_tree_quad.insert("", "end", values=fila, tags=(tag,))

            for item in tac_tree_triple.get_children():
                tac_tree_triple.delete(item)
            triples = quads_to_triples(rutina.quads)
            for i, fila in enumerate(triples_to_table_rows(triples)):
                tag = "par" if i % 2 == 0 else "impar"
                valores = list(fila)
                valores[0] = f"({valores[0]})"
                tac_tree_triple.insert("", "end", values=valores, tags=(tag,))

        _refrescar_tablas()

        ctk.CTkButton(
            ventana,
            text="Cerrar",
            fg_color="#37474f",
            hover_color="#455a64",
            width=110,
            command=ventana.destroy,
        ).pack(pady=(0, 16))
        

    def _detener(self):
        """Detiene la reproducción de audio MIDI en curso."""
        pygame.mixer.music.stop()
        self._log("Reproducción detenida.")

    def _calcular_columna(self, source: str, token) -> int:
        """
        Calcula la columna 1-indexada de un token dentro de su línea.
        Usa el mismo algoritmo que _find_column() del lexer para consistencia
        en los mensajes de error de la validación post-léxica.
        """
        line_start = source.rfind("\n", 0, token.lexpos) + 1
        return token.lexpos - line_start + 1

    def _mock_tokens(self) -> list:
        """
        Genera una lista de tokens falsos para demostración cuando el módulo
        beatscript.lexer no está disponible (ImportError). Permite que el IDE
        arranque y muestre la interfaz aunque el paquete no esté instalado.
        """
        class FakeTok:
            def __init__(self, t, v, l, p):
                self.type = t
                self.value = v
                self.lineno = l
                self.lexpos = p

        return [
            FakeTok("TEMPO_KW",      "tempo",       1,  0),
            FakeTok("NUMBER",         120,           1,  6),
            FakeTok("INSTRUMENT_KW", "instrument",  3, 11),
            FakeTok("INSTR_NAME",    "piano",       3, 22),
            FakeTok("TRACK_KW",      "track",       5, 28),
            FakeTok("IDENTIFIER",    "melody",      5, 34),
            FakeTok("LBRACE",        "{",           5, 41),
            FakeTok("NOTE",          "C4",          6, 47),
            FakeTok("DURATION",      "negra",       6, 50),
            FakeTok("NOTE",          "D4",          7, 56),
            FakeTok("DURATION",      "negra",       7, 59),
            FakeTok("RBRACE",        "}",           8, 65),
        ]

    def _log(self, mensaje: str, clear: bool = False):
        """
        Escribe un mensaje en la consola del IDE.

        La consola está en modo 'disabled' la mayor parte del tiempo para
        evitar edición por el usuario. Este método la habilita temporalmente,
        inserta el mensaje y la vuelve a deshabilitar.

        Args:
            mensaje: Texto a mostrar. Si es cadena vacía, no inserta nada.
            clear:   Si True, limpia todo el contenido previo antes de escribir.
        """
        self.consola.configure(state="normal")
        if clear:
            self.consola.delete("1.0", "end")
        if mensaje:
            self.consola.insert("end", mensaje + "\n")
        self.consola.see("end")   # Auto-scroll al final
        self.consola.configure(state="disabled")

    def _cargar_ejemplo(self):
        ejemplo = """\
## Oda a la Alegría — BeatScript
tempo 110
volume 80

instrument violin
    
track melodia {
  E4 negra
  E4 negra
  F4 negra
  G4 negra
  G4 negra
  F4 negra
  E4 negra
  D4 negra
  C4 negra
  C4 negra
  D4 negra
  E4 negra
  E4 blanca
  D4 blanca
}

"""
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", ejemplo)
        self._actualizar_estado()
        self.after(100, self._actualizar_lineas)
        self.after(100, self._aplicar_resaltado)


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = BeatScriptIDE()
    app.mainloop()


