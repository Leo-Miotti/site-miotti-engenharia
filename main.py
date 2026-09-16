from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, render_template, request, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent

WHATSAPP_PADRAO = "5555999358573"

SERVICOS = {
    "arquitetonico": "Projeto Arquitetônico",
    "estrutural": "Projeto Estrutural",
    "regularizacao": "Regularização de Imóveis",
    "obra": "Execução de Obra",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

# Controle simples de repetição: guarda o último envio por IP na memória.
_ultimos_envios: dict[str, float] = {}
INTERVALO_MINIMO_SEGUNDOS = 20

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)

    config_name = config_name or os.getenv("FLASK_ENV", "development")
    em_producao = config_name == "production"

    # 1. Tratamos a URL do banco (pega do Neon se houver, senão usa um local)
    database_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    # 2. As configurações do site juntamente com as do banco
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "troque-esta-chave-em-producao"),
        TEMPLATES_AUTO_RELOAD=not em_producao,
        SEND_FILE_MAX_AGE_DEFAULT=31536000 if em_producao else 0,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=em_producao,
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
        WHATSAPP=os.getenv("WHATSAPP", WHATSAPP_PADRAO),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    # 3. Inicializamos o banco e o gerenciador de login no app
    db.init_app(app)
    login_manager.init_app(app)

    registrar_rotas(app)
    registrar_erros(app)
    registrar_contexto(app)
    registrar_cabecalhos(app)

    # 4. Garante a criação das tabelas ao iniciar
    with app.app_context():
        db.create_all()

    return app


# --- Modelo de Dados (Tabela de Clientes) ----------------------------------
class Cliente(db.Model, UserMixin):
    __tablename__ = 'clientes'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    criado_em = db.Column(db.DateTime, server_default=db.func.now())


@login_manager.user_loader
def load_user(user_id):
    return Cliente.query.get(int(user_id))

# --- Modelo de Projetos/Obras ----------------------------------------------
class Projeto(db.Model):
    __tablename__ = 'projetos'
    
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)         # Ex: Projeto Estrutural - Residência
    status = db.Column(db.String(100), nullable=False)         # Ex: Em andamento, Concluído, Em análise
    descricao = db.Column(db.Text, nullable=True)              # Detalhes do projeto
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    
    # Cria uma relação fácil para puxar os dados do cliente direto pelo projeto
    cliente = db.relationship('Cliente', backref=db.backref('projetos', lazy=True))


# --- Rotas -----------------------------------------------------------------
def registrar_rotas(app: Flask) -> None:
    @app.route("/")
    def pagina_inicial():
        return render_template("index.html", servicos=SERVICOS)

    @app.route("/cadastro", methods=["GET", "POST"])
    def cadastro():
        if current_user.is_authenticated:
            return redirect(url_for('painel'))
            
        if request.method == "POST":
            nome = request.form.get("nome")
            email = request.form.get("email")
            senha = request.form.get("senha")
            
            # Verifica se o e-mail já existe
            cliente_existe = Cliente.query.filter_by(email=email).first()
            if cliente_existe:
                return render_template("cadastro.html", erro="Este e-mail já está cadastrado.")
                
            # Cria a senha criptografada (hash)
            hash_senha = generate_password_hash(senha)
            
            novo_cliente = Cliente(nome=nome, email=email, senha_hash=hash_senha)
            db.session.add(novo_cliente)
            db.session.commit()
            
            return redirect(url_for('login'))
            
        return render_template("cadastro.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('painel'))
            
        if request.method == "POST":
            email = request.form.get("email")
            senha = request.form.get("senha")
            
            cliente = Cliente.query.filter_by(email=email).first()
            
            # Verifica se o cliente existe e se a senha bate com o hash salvo
            if cliente and check_password_hash(cliente.senha_hash, senha):
                login_user(cliente)
                return redirect(url_for('painel'))
                
            return render_template("login.html", erro="E-mail ou senha incorretos.")
            
        return render_template("login.html")      

    @app.route("/painel")
    @login_required # Só entra aqui quem estiver logado!
    def painel():
        return render_template("painel.html", nome=current_user.nome)

    # --- Painel Administrativo (Gerenciar Obras dos Clientes) ---------------
    @app.route("/admin", methods=["GET", "POST"])
    @login_required
    def admin_painel():
        
        emails_autorizados = ["leonardorafaelmiotti@gmail.com", "renan.m.miotti@gmail.com"]
        
        if current_user.email not in emails_autorizados: 
            flash("Acesso não autorizado.", "erro")
            return redirect(url_for('painel'))
        
        if request.method == "POST":
            titulo = request.form.get("titulo")
            status = request.form.get("status")
            descricao = request.form.get("descricao")
            cliente_id = request.form.get("cliente_id")

            novo_projeto = Projeto(
                titulo=titulo, 
                status=status, 
                descricao=descricao, 
                cliente_id=cliente_id
            )
            db.session.add(novo_projeto)
            db.session.commit()
            return redirect(url_for('admin_painel'))

        # Busca todos os clientes e projetos cadastrados para gerenciar
        clientes = Cliente.query.all()
        projetos = Projeto.query.all()
        return render_template("admin.html", clientes=clientes, projetos=projetos)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('pagina_inicial'))

    @app.post("/api/orcamento")
    def receber_orcamento():
        dados = request.get_json(silent=True) or request.form

        # Campo invisível preenchido só por robô.
        if (dados.get("website") or "").strip():
            return jsonify(ok=True, whatsapp=None), 200

        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0]
        agora = time.time()
        if agora - _ultimos_envios.get(ip, 0) < INTERVALO_MINIMO_SEGUNDOS:
            return jsonify(ok=False, erros={"geral": "Aguarde alguns segundos e tente de novo."}), 429

        campos, erros = validar(dados)
        if erros:
            return jsonify(ok=False, erros=erros), 400

        _ultimos_envios[ip] = agora

        # Tudo validado, retorna o link do WhatsApp
        return jsonify(ok=True, whatsapp=montar_link_whatsapp(app, campos)), 200

    @app.route("/saude")
    def saude():
        return {"status": "ok"}, 200

    @app.route("/robots.txt")
    def robots():
        corpo = f"User-agent: *\nAllow: /\nSitemap: {url_for('sitemap', _external=True)}\n"
        return Response(corpo, mimetype="text/plain")

    @app.route("/sitemap.xml")
    def sitemap():
        hoje = datetime.now().strftime("%Y-%m-%d")
        corpo = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{url_for('pagina_inicial', _external=True)}</loc>"
            f"<lastmod>{hoje}</lastmod><priority>1.0</priority></url>"
            "</urlset>"
        )
        return Response(corpo, mimetype="application/xml")


# --- Validação -------------------------------------------------------------
def validar(dados) -> tuple[dict, dict]:
    erros: dict[str, str] = {}

    def texto(chave: str, limite: int = 200) -> str:
        return (dados.get(chave) or "").strip()[:limite]

    nome = texto("nome", 120)
    email = texto("email", 160)
    telefone = texto("telefone", 40)
    area = texto("area", 20)
    comentario = texto("comentario", 1500)

    brutos = dados.getlist("servico") if hasattr(dados, "getlist") else dados.get("servico", [])
    if isinstance(brutos, str):
        brutos = [brutos]
    servicos = [s for s in brutos if s in SERVICOS]

    if len(nome) < 2:
        erros["nome"] = "Informe seu nome."
    if not EMAIL_RE.match(email):
        erros["email"] = "Informe um e-mail válido."
    if len(re.sub(r"\D", "", telefone)) < 10:
        erros["telefone"] = "Informe o telefone com DDD."
    if area and not re.match(r"^\d{1,6}([.,]\d{1,2})?$", area):
        erros["area"] = "Use apenas números, como 120."
    if not servicos:
        erros["servico"] = "Escolha pelo menos um serviço."

    campos = {
        "nome": nome,
        "email": email,
        "telefone": telefone,
        "area": area,
        "comentario": comentario,
        "servicos": servicos,
    }
    return campos, erros


def montar_link_whatsapp(app: Flask, c: dict) -> str:
    linhas = [
        "Olá! Gostaria de solicitar um orçamento para a Miotti Engenharia.",
        "",
        f"*Nome:* {c['nome']}",
        f"*Telefone:* {c['telefone']}",
        f"*E-mail:* {c['email']}",
    ]
    if c["area"]:
        linhas.append(f"*Área estimada:* {c['area']} m²")
    linhas.append("*Serviços:* " + ", ".join(SERVICOS[s] for s in c["servicos"]))
    if c["comentario"]:
        linhas.append(f"*Observações:* {c['comentario']}")

    texto = quote("\n".join(linhas))
    return f"https://wa.me/{app.config['WHATSAPP']}?text={texto}"


# --- Erros -----------------------------------------------------------------
def registrar_erros(app: Flask) -> None:
    @app.errorhandler(404)
    def nao_encontrado(_erro):
        return render_template("erros/404.html"), 404

    @app.errorhandler(500)
    def erro_interno(_erro):
        app.logger.exception("Erro interno não tratado")
        return render_template("erros/500.html"), 500


# --- Contexto dos templates ------------------------------------------------
def registrar_contexto(app: Flask) -> None:
    @app.context_processor
    def globais():
        return {
            "ano": datetime.now().year,
            "whatsapp": app.config["WHATSAPP"],
        }

    @app.template_global()
    def estatico(arquivo: str) -> str:
        """url_for('static') com a data do arquivo na URL."""
        caminho = BASE_DIR / "static" / arquivo
        versao = int(caminho.stat().st_mtime) if caminho.exists() else 0
        return url_for("static", filename=arquivo, v=versao)


# --- Segurança -------------------------------------------------------------
def registrar_cabecalhos(app: Flask) -> None:
    @app.after_request
    def aplicar(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resposta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resposta


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_ENV", "development") == "development",
    )