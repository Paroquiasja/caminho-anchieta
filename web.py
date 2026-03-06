from flask import Flask, request, render_template_string, session, redirect, url_for
import re
import os
import random
from datetime import date, datetime
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import unicodedata

DB_PATH = "paroquia.db"

# ---------------- BANCO ----------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    # Usuários
    conn.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT UNIQUE,
        senha_hash TEXT,
        perfil TEXT,
        ativo INTEGER DEFAULT 1,
        permissoes TEXT,
        trocar_senha INTEGER DEFAULT 0
    )
    """)

    # Aprendizado automático
    conn.execute("""
    CREATE TABLE IF NOT EXISTS aprendizado (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pergunta TEXT UNIQUE,
        contador INTEGER DEFAULT 1
    )
    """)

    # Histórico
    conn.execute("""
    CREATE TABLE IF NOT EXISTS historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_hora TEXT,
        pergunta TEXT,
        resposta TEXT
    )
    """)

    # Logs
    conn.execute("""
    CREATE TABLE IF NOT EXISTS logs_admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_hora TEXT,
        usuario_admin TEXT,
        acao TEXT,
        alvo TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS topicos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        secao_id INTEGER,
        titulo TEXT,
        palavras_chave TEXT,
        resposta TEXT,
        FOREIGN KEY (secao_id) REFERENCES secoes(id)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS secoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL
    )
    """)

# 🔐 Criar admin padrão se não existir
    cur = conn.execute("SELECT id FROM usuarios WHERE usuario='admin'")
    admin = cur.fetchone()

    if not admin:
        conn.execute("""
            INSERT INTO usuarios 
            (usuario, senha_hash, perfil, ativo, permissoes, trocar_senha)
            VALUES (?, ?, ?, 1, ?, 0)
        """, (
            "admin",
            generate_password_hash("1234"),
            "admin",
            "editor,logs,usuarios"
        ))
        conn.commit()

# 🔹 Criar seções padrão
    secoes_padrao = ["liturgia", "cic", "santos", "sacramentos", "paroquia"]

    for nome in secoes_padrao:
        try:
            conn.execute("INSERT INTO secoes (nome) VALUES (?)", (nome,))
        except:
            pass

    conn.commit()

    conn.commit()
    conn.close()


# Inicializa banco
init_db()



# ---------------- APRENDIZADO ----------------

def registrar_aprendizado(pergunta):
    conn = get_db()

    cur = conn.execute(
        "SELECT id, contador FROM aprendizado WHERE pergunta=?",
        (pergunta,)
    )
    row = cur.fetchone()

    if row:
        conn.execute(
            "UPDATE aprendizado SET contador=? WHERE id=?",
            (row["contador"] + 1, row["id"])
        )
    else:
        conn.execute(
            "INSERT INTO aprendizado (pergunta, contador) VALUES (?, 1)",
            (pergunta,)
        )

    conn.commit()
    conn.close()

def perguntas_importantes():

    conn = get_db()

    cur = conn.execute("""
        SELECT pergunta, contador
        FROM aprendizado
        WHERE contador >= 3
        ORDER BY contador DESC
        LIMIT 10
    """)

    dados = cur.fetchall()

    conn.close()

    return dados

def perguntas_criticas():

    conn = get_db()

    cur = conn.execute("""
        SELECT id, pergunta, contador
        FROM aprendizado
        WHERE contador >= 5
        ORDER BY contador DESC
    """)

    dados = cur.fetchall()

    conn.close()

    return dados


# ---------------- USUÁRIOS ----------------

def get_usuario(usuario):
    conn = get_db()
    cur = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,))
    user = cur.fetchone()
    conn.close()
    return user


def verificar_senha(senha_digitada, senha_hash_banco):
    return check_password_hash(senha_hash_banco, senha_digitada)


# ---------------- HISTÓRICO ----------------

def salvar_historico(pergunta, resposta):
    conn = get_db()
    conn.execute(
        "INSERT INTO historico (data_hora, pergunta, resposta) VALUES (?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pergunta, resposta)
    )
    conn.commit()
    conn.close()


# ---------------- LOGS ----------------

def registrar_log(acao, alvo):
    try:
        admin = session.get("usuario", "desconhecido")
        conn = get_db()
        conn.execute(
            "INSERT INTO logs_admin (data_hora, usuario_admin, acao, alvo) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), admin, acao, alvo)
        )
        conn.commit()
        conn.close()
    except:
        pass


# ---------------- PERMISSÕES ----------------

def tem_nivel(nivel_necessario):

    perfil = session.get("perfil")

    hierarquia = {
        "admin": 4,
        "coordenador": 3,
        "editor": 2,
        "visualizador": 1
    }

    return hierarquia.get(perfil, 0) >= hierarquia.get(nivel_necessario, 0)

def pode_editar_secao(secao_nome):

    # Admin pode tudo
    if session.get("perfil") == "admin":
        return True

    permissoes = session.get("permissoes", "")

    lista = [p.strip().lower() for p in permissoes.split(",") if p.strip()]

    return secao_nome.lower() in lista

# ---------- Config ----------
STOPWORDS = {
    "o","a","os","as","de","do","da","dos","das","em","no","na","nos","nas",
    "para","por","que","e","ou","um","uma","como","é","ser","ter","ao","aos",
    "qual","quais","quando","onde","porque","sobre","me","se"
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "paroquia-secret-key")

# ---------- Versículos ----------
VERSICULOS = [
    "“Eu sou o caminho, a verdade e a vida.” (Jo 14,6)",
    "“O Senhor é meu pastor, nada me faltará.” (Sl 23,1)",
    "“Tudo posso naquele que me fortalece.” (Fl 4,13)",
    "“Alegrai-vos sempre no Senhor.” (Fl 4,4)",
    "“Vinde a mim, todos os que estais cansados.” (Mt 11,28)",
    "“O amor tudo suporta, tudo crê, tudo espera.” (1Cor 13,7)"
]

def versiculo_do_dia():
    hoje = date.today().toordinal()
    random.seed(hoje)
    return random.choice(VERSICULOS)

# ---------- Backup ----------
def backup_arquivo(caminho):
    os.makedirs("backups", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = os.path.basename(caminho).replace(".txt", "")
    nome_backup = f"backups/{nome}_{timestamp}.txt"
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()
        with open(nome_backup, "w", encoding="utf-8") as b:
            b.write(conteudo)

def backup_banco():

    try:

        os.makedirs("backups", exist_ok=True)

        hoje = datetime.now().strftime("%Y-%m-%d")

        origem = DB_PATH
        destino = f"backups/paroquia_{hoje}.db"

        if os.path.exists(origem):

            import shutil
            shutil.copy2(origem, destino)

    except Exception as e:
        print("Erro backup:", e)


# cria backup ao iniciar sistema

backup_banco()

# ---------- Base ----------

def carregar_base():

    conn = get_db()

    cur = conn.execute("""
        SELECT 
            t.id,
            t.titulo,
            t.palavras_chave,
            t.resposta,
            s.nome AS secao_nome
        FROM topicos t
        JOIN secoes s ON t.secao_id = s.id
    """)

    registros = cur.fetchall()
    conn.close()

    base = []

    for r in registros:

        if not r["palavras_chave"]:
            continue

        palavras = [p.strip() for p in r["palavras_chave"].split(",")]

        base.append({
            "palavras": palavras,
            "resposta": r["resposta"],
            "secao": r["secao_nome"],
            "titulo": r["titulo"]
        })

    return base

base = carregar_base()

# ---------- Util ----------

def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = texto.encode("ascii", "ignore").decode("utf-8")
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    palavras = texto.split()
    palavras = [p for p in palavras if p not in STOPWORDS]
    return palavras

def calcular_similaridade(palavras_pergunta, palavras_topico):

    if not palavras_pergunta or not palavras_topico:
        return 0

    intersecao = set(palavras_pergunta) & set(palavras_topico)

    score = len(intersecao) / max(len(palavras_pergunta), 1)

    return score

def sugerir_palavras_chave(pergunta):

    texto = pergunta.lower()

    palavras = re.findall(r'\w+', texto)

    palavras = [
        p for p in palavras
        if p not in STOPWORDS and len(p) > 3
    ]

    # remove duplicadas
    palavras_unicas = list(dict.fromkeys(palavras))

    return ", ".join(palavras_unicas[:6])

def sugerir_resposta(pergunta):

    p = pergunta.lower()

    if "batismo" in p:
        return """O Batismo é o primeiro sacramento da vida cristã.
Ele nos torna filhos de Deus e membros da Igreja.

Catecismo da Igreja Católica §1213."""

    if "confissao" in p or "confessar" in p:
        return """A confissão é o sacramento do perdão dos pecados
cometidos após o batismo.

Catecismo da Igreja Católica §1422."""

    if "maria" in p:
        return """Maria é a Mãe de Jesus e modelo perfeito de fé.
Os católicos a veneram como Mãe da Igreja e intercessora."""

    return ""


def escolher_resposta(pergunta):

    palavras_pergunta = normalizar(pergunta)

    GENERICAS = {"santo", "santa", "sao", "igreja", "paroquia"}

    palavras_pergunta = [
        p for p in palavras_pergunta if p not in GENERICAS
    ]

    if not palavras_pergunta:
        registrar_aprendizado(pergunta)
        return "Não encontrei detalhes suficientes na pergunta."

    melhor_resposta = None
    melhor_score = 0

    for topico in base:

        palavras_topico = []

        for p in topico["palavras"]:
            palavras_topico.extend(normalizar(p))

        score = calcular_similaridade(palavras_pergunta, palavras_topico)

        if score > melhor_score:
            melhor_score = score
            melhor_resposta = topico["resposta"]

    if melhor_score >= 0.5:
        return melhor_resposta

    registrar_aprendizado(pergunta)

    return "Ainda não encontrei essa resposta na minha base. Sua pergunta foi registrada para melhoria futura."

# ---------- HTML ----------
HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Caminho de Anchieta</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/static/favicon.ico" type="image/x-icon">
<style>
body { margin:0; font-family: Arial, sans-serif; background:#0b2a4a; }

/* Topo */
.topo {
    background:white; padding:15px 20px; display:flex; align-items:center; justify-content:space-between;
    border-bottom:4px solid #d4a017; box-shadow:0 2px 8px rgba(0,0,0,0.15);
}
.topo img { height:90px; }
.titulo-container { text-align:center; flex:1; }
.titulo { font-size:32px; font-weight:bold; color:#0b2a4a; }
.subtitulo { font-size:14px; color:#555; }

/* Layout */
.container { display:flex; min-height: calc(100vh - 140px); }

/* Menu */
.menu {
    width:220px; background:#123c6b; padding:15px; color:white;
}
.menu h3 { margin-top:0; border-bottom:1px solid #ffffff55; padding-bottom:5px; }
.menu button {
    width:100%; margin:6px 0; padding:10px; border:none; border-radius:6px;
    background:#d4a017; color:#0b2a4a; font-weight:bold; cursor:pointer;
}
.menu button:hover { background:#e6b737; }

/* Chat */
.chat-area { flex:1; padding:20px; }
.chat-box {
    background:white; border-radius:12px; padding:15px; height:60vh; overflow-y:auto;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
}

/* Versículo */
.versiculo {
    background:#d4a017; color:#0b2a4a; padding:10px; border-radius:8px; margin-bottom:10px;
    text-align:center; font-weight:bold;
}

/* Balões */
.msg { margin:10px 0; display:flex; }
.msg.user { justify-content:flex-end; }
.msg.ia { justify-content:flex-start; }
.balao { max-width:70%; padding:10px 14px; border-radius:15px; }
.user .balao { background:#0b2a4a; color:white; border-bottom-right-radius:0; }
.ia .balao { background:#e9ecef; color:#000; border-bottom-left-radius:0; }

/* Entrada */
.form-area { margin-top:10px; display:flex; gap:10px; }
.form-area input {
    flex:1; padding:12px; border-radius:8px; border:1px solid #ccc;
}
.form-area button {
    padding:12px 16px;
    border-radius:8px;
    border:none;
    background:#d4a017;   /* mesma cor da lateral */
    color:#0b2a4a;
    font-weight:bold;
    cursor:pointer;
}

.form-area button:hover {
    background:#e6b737;   /* mesmo hover da lateral */
}

@media (max-width:700px) {
    .menu { display:none; }
    .topo img { height:60px; }
    .titulo { font-size:24px; }
}
</style>
</head>
<body>

<div class="topo">
    <img src="/static/logo_paroquia.png">
    <div class="titulo-container">
        <div class="titulo">Caminho de Anchieta</div>
        <div class="subtitulo">Assistente da Paróquia São José de Anchieta</div>
    </div>
    <img src="/static/logo_pascom.png">
</div>

<div class="container">

    <div class="menu">
        <h3>Menu</h3>
        <form method="post"><input type="hidden" name="pergunta" value="Qual o horário da missa?"><button>Missas</button></form>
        <form method="post"><input type="hidden" name="pergunta" value="O que é o Batismo?"><button>Batismo</button></form>
        <form method="post"><input type="hidden" name="pergunta" value="Como entrar na catequese?"><button>Catequese</button></form>
        <form method="post"><input type="hidden" name="pergunta" value="Qual o contato da secretaria paroquial?"><button>Contato</button></form>
        <form method="post" action="/limpar"><button>Limpar conversa</button></form>
        <br>
        <a href="/login" style="color:white;">Área Administrativa</a>
    </div>

    <div class="chat-area">
        <div class="versiculo">Versículo do dia: {{ versiculo }}</div>

        <div class="chat-box">
            {% for autor, texto in historico %}
                <div class="msg {{ autor }}">
                    <div class="balao">{{ texto }}</div>
                </div>
            {% endfor %}
        </div>

        <form method="post" class="form-area">
            <input type="text" name="pergunta" placeholder="Digite sua pergunta...">
            <button type="submit">Enviar</button>
        </form>
    </div>

</div>

</body>
</html>
"""

MENSAGEM_INICIAL = (
    "Olá! 👋 Seja bem-vindo ao Caminho de Anchieta.\n\n"
    "Sou o assistente da Paróquia São José de Anchieta.\n"
    "Você pode usar o menu ao lado ou digitar sua pergunta."
)

# ---------- Rotas ----------
@app.route("/", methods=["GET", "POST"])
def index():
    if "historico" not in session:
        session["historico"] = [("ia", MENSAGEM_INICIAL)]

    if request.method == "POST":
        pergunta = request.form.get("pergunta", "").strip()
        if pergunta:
            historico = session["historico"]
            historico.append(("user", pergunta))
            resposta = escolher_resposta(pergunta)
            historico.append(("ia", resposta))
            session["historico"] = historico

            salvar_historico(pergunta, resposta)

    return render_template_string(HTML, historico=session["historico"], versiculo=versiculo_do_dia())

@app.route("/limpar", methods=["POST"])
def limpar():
    session["historico"] = [("ia", MENSAGEM_INICIAL)]
    return redirect(url_for("index"))

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""

    if request.method == "POST":
        user = request.form.get("usuario")
        senha = request.form.get("senha")

        u = get_usuario(user)

        if u and (u["ativo"] is None or u["ativo"] == 1) and verificar_senha(senha, u["senha_hash"]):

            # 🔐 Se precisar trocar senha
            if u["trocar_senha"] == 1:
                session["trocar_senha"] = True
                session["usuario_id"] = u["id"]
                return redirect(url_for("trocar_senha"))

            # Login normal
            session["logado"] = True
            session["usuario"] = u["usuario"]
            session["perfil"] = u["perfil"]
            session["permissoes"] = u["permissoes"] or ""
            session["historico"] = []

            return redirect(url_for("admin"))

        else:
            erro = "Usuário, senha inválidos ou usuário desativado"

    return render_template_string(f"""
    <html>
    <head>
        <title>Login - Caminho de Anchieta</title>
        <style>
            body {{ font-family: Arial; background:#0b2a4a; color:#0b2a4a; }}
            .box {{ background:white; padding:20px; border-radius:10px; width:300px; margin:80px auto; text-align:center; }}
            input {{ width:90%; padding:10px; margin:8px 0; }}
            button {{ padding:10px 15px; font-weight:bold; }}
            .erro {{ color:red; }}
        </style>
    </head>
    <body>
        <div class="box">
            <h2>Login Administrativo</h2>
            <form method="post">
                <input type="text" name="usuario" placeholder="Usuário" required><br>
                <input type="password" name="senha" placeholder="Senha" required><br>
                <button type="submit">Entrar</button>
            </form>
            <p class="erro">{erro}</p>
            <a href="/">Voltar ao chat</a>
        </div>
    </body>
    </html>
    """)

@app.route("/admin/minha_senha", methods=["GET", "POST"])
def minha_senha():

    if not session.get("logado"):
        return redirect(url_for("login"))

    mensagem = ""
    erro = ""

    if request.method == "POST":
        atual = request.form.get("senha_atual")
        nova = request.form.get("nova_senha")
        confirmar = request.form.get("confirmar_senha")

        u = get_usuario(session["usuario"])

        if not check_password_hash(u["senha_hash"], atual):
            erro = "Senha atual incorreta"

        elif nova != confirmar:
            erro = "As novas senhas não conferem"

        elif len(nova) < 4:
            erro = "A senha deve ter pelo menos 4 caracteres"

        else:
            conn = get_db()
            conn.execute(
                "UPDATE usuarios SET senha_hash=? WHERE id=?",
                (generate_password_hash(nova), u["id"])
            )
            conn.commit()
            conn.close()

            mensagem = "Senha alterada com sucesso!"

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Alterar Minha Senha</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family: Arial; background:#0b2a4a; }
.topo { background:white; padding:15px; border-bottom:4px solid #d4a017; font-size:24px; font-weight:bold; color:#0b2a4a; text-align:center; }
.container { padding:40px; }
.box { background:white; padding:30px; border-radius:12px; max-width:450px; margin:auto; box-shadow:0 4px 10px rgba(0,0,0,0.2); }
input { width:100%; padding:10px; margin:8px 0; border-radius:6px; border:1px solid #ccc; }
button { width:100%; padding:10px; border-radius:8px; border:none; background:#d4a017; font-weight:bold; color:#0b2a4a; cursor:pointer; }
button:hover { background:#e6b737; }
.msg { color:green; font-weight:bold; margin-bottom:10px; }
.erro { color:red; font-weight:bold; margin-bottom:10px; }
.voltar { display:block; margin-top:15px; text-align:center; font-weight:bold; color:#0b2a4a; text-decoration:none; }
</style>
</head>
<body>

<div class="topo">🔐 Alterar Minha Senha</div>

<div class="container">
<div class="box">

{% if mensagem %}<div class="msg">{{ mensagem }}</div>{% endif %}
{% if erro %}<div class="erro">{{ erro }}</div>{% endif %}

<form method="post">
<input type="password" name="senha_atual" placeholder="Senha atual" required>
<input type="password" name="nova_senha" placeholder="Nova senha" required>
<input type="password" name="confirmar_senha" placeholder="Confirmar nova senha" required>
<button type="submit">Alterar senha</button>
</form>

<a class="voltar" href="/admin">⬅ Voltar ao painel</a>

</div>
</div>

</body>
</html>
""", mensagem=mensagem, erro=erro)

@app.route("/trocar_senha", methods=["GET", "POST"])
def trocar_senha():

    if not session.get("trocar_senha"):
        return redirect(url_for("index"))

    if request.method == "POST":
        nova = request.form.get("nova_senha")
        confirmar = request.form.get("confirmar_senha")

        if not nova or nova != confirmar:
            erro = "As senhas não conferem"
        else:
            conn = get_db()
            conn.execute(
                "UPDATE usuarios SET senha_hash=?, trocar_senha=0 WHERE id=?",
                (generate_password_hash(nova), session["usuario_id"])
            )
            conn.commit()

            cur = conn.execute("SELECT * FROM usuarios WHERE id=?", (session["usuario_id"],))
            u = cur.fetchone()
            conn.close()

            session.pop("trocar_senha", None)
            session["logado"] = True
            session["usuario"] = u["usuario"]
            session["perfil"] = u["perfil"]
            session["permissoes"] = u["permissoes"] or ""
            session["historico"] = []

            return redirect(url_for("admin"))
    else:
        erro = ""

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Troca de Senha Obrigatória</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family: Arial; background:#0b2a4a; }
.topo { background:white; padding:15px; border-bottom:4px solid #d4a017; font-size:24px; font-weight:bold; color:#0b2a4a; text-align:center; }
.container { padding:40px; }
.box { background:white; padding:30px; border-radius:12px; max-width:400px; margin:auto; box-shadow:0 4px 10px rgba(0,0,0,0.2); }
input { width:100%; padding:10px; margin:8px 0; border-radius:6px; border:1px solid #ccc; }
button { width:100%; padding:10px; border-radius:8px; border:none; background:#d4a017; font-weight:bold; color:#0b2a4a; cursor:pointer; }
button:hover { background:#e6b737; }
.erro { color:red; font-weight:bold; margin-bottom:10px; }
</style>
</head>
<body>

<div class="topo">🔐 Troca de Senha Obrigatória</div>

<div class="container">
<div class="box">

{% if erro %}<div class="erro">{{ erro }}</div>{% endif %}

<form method="post">
<input type="password" name="nova_senha" placeholder="Nova senha" required>
<input type="password" name="confirmar_senha" placeholder="Confirmar senha" required>
<button type="submit">Salvar nova senha</button>
</form>

</div>
</div>

</body>
</html>
""", erro=erro)
 #=======================================================ADMIN=================================================

@app.route("/admin")
def admin():

    if not session.get("logado"):
        return redirect(url_for("login"))

    usuario = session.get("usuario", "")
    perfil = session.get("perfil", "")

    conn = get_db()

    # 👥 Total usuários
    cur = conn.execute("SELECT COUNT(*) as total FROM usuarios")
    total_usuarios = cur.fetchone()["total"]

    # 🧾 Total logs
    cur = conn.execute("SELECT COUNT(*) as total FROM logs_admin")
    total_logs = cur.fetchone()["total"]

    # 📚 Total tópicos (AGORA CORRETO)
    cur = conn.execute("SELECT COUNT(*) as total FROM topicos")
    total_topicos = cur.fetchone()["total"]

    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Painel Administrativo - Caminho de Anchieta</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family: Arial, sans-serif; background:#0b2a4a; }

.topo {
    background:white; padding:15px 20px; display:flex; align-items:center; justify-content:space-between;
    border-bottom:4px solid #d4a017;
}
.topo img { height:70px; }
.titulo { font-size:26px; font-weight:bold; color:#0b2a4a; }

.container { padding:30px; }

.info {
    color:white;
    margin-bottom:20px;
}

.grid {
    display:grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap:20px;
}

.card {
    background:white;
    border-radius:12px;
    padding:20px;
    text-align:center;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
}

.card h3 { margin-top:0; color:#0b2a4a; }

.card {
    background:white;
    border-radius:12px;
    padding:20px;
    text-align:center;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
    display:flex;
    flex-direction:column;
    justify-content:space-between;
}

.card a {
    margin-top:auto;
    padding:10px 15px;
    background:#d4a017;
    color:#0b2a4a;
    text-decoration:none;
    border-radius:8px;
    font-weight:bold;
}

.metricas {
    display:grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap:20px;
    margin-bottom:30px;
}

.metrica {
    background:#d4a017;
    border-radius:12px;
    padding:20px;
    text-align:center;
    color:#0b2a4a;
    font-weight:bold;
}

.metrica h2 {
    margin:0;
    font-size:32px;
}
</style>
</head>
<body>

<div class="topo">
    <img src="/static/logo_paroquia.png">
    <div class="titulo">Painel Administrativo - Caminho de Anchieta</div>
    <img src="/static/logo_pascom.png">
</div>

<div class="container">

    <div class="info">
        Usuário: <b>{{ usuario }}</b> | Perfil: <b>{{ perfil }}</b>
    </div>

    <div class="metricas">
        <div class="metrica">
            <h2>{{ total_usuarios }}</h2>
            <p>Usuários</p>
        </div>

        <div class="metrica">
            <h2>{{ total_logs }}</h2>
            <p>Logs</p>
        </div>

        <div class="metrica">
            <h2>{{ total_topicos }}</h2>
            <p>Tópicos na Base</p>
        </div>
    </div>

    <div class="grid">

    {% if perfil == "admin" or "editor" in session.get("permissoes","") %}
    <div class="card">
        <h3>📚 Tópicos</h3>
        <p>Gerenciar base da IA.</p>
        <a href="/admin/topicos">Acessar</a>
    </div>
    {% endif %}

    {% if perfil == "admin" %}
    <div class="card">
        <h3>🧠 Aprendizado</h3>
        <p>Perguntas ainda não cadastradas.</p>
        <a href="/admin/aprendizado">Acessar</a>
    </div>
    <div class="card">
       <h3>📊 Radar Pastoral</h3>
       <p>Perguntas frequentes da comunidade.</p>
       <a href="/admin/radar">Acessar</a>
    </div>
    <div class="card">
       <h3>🔥 Perguntas Importantes</h3>
       <p>Perguntas repetidas pela comunidade.</p>
       <a href="/admin/perguntas_criticas">Acessar</a>
    </div>
    {% endif %}

    {% if perfil == "admin" or "usuarios" in session.get("permissoes","") %}
    <div class="card">
        <h3>👥 Usuários</h3>
        <p>Gerenciar usuários do sistema.</p>
        <a href="/admin/usuarios">Acessar</a>
    </div>
    {% endif %}

    {% if perfil == "admin" or "logs" in session.get("permissoes","") %}
    <div class="card">
        <h3>📜 Logs</h3>
        <p>Ver ações administrativas.</p>
        <a href="/admin/logs">Acessar</a>
    </div>
    {% endif %}

    <div class="card">
        <h3>🔐 Minha Senha</h3>
        <p>Alterar minha senha.</p>
        <a href="/admin/minha_senha">Alterar</a>
    </div>

    <div class="card">
        <h3>💬 Voltar ao Chat</h3>
        <p>Retornar ao assistente.</p>
        <a href="/">Voltar</a>
    </div>

    <div class="card">
        <h3>🚪 Logout</h3>
        <p>Encerrar sessão.</p>
        <a href="/logout">Sair</a>
    </div>

    <div class="card">
       <h3>💾 Backup</h3>
       <p>Salvar cópia do banco.</p>
       <a href="/admin/backup">Executar</a>
    </div>

    {% if perfil == "admin" %}
    <div class="card">
        <h3>📁 Seções</h3>
        <p>Criar e organizar áreas.</p>
        <a href="/admin/secoes">Acessar</a>
    </div>
    {% endif %}

    </div>

    </div>
</div>

</body>
</html>
""",
        usuario=usuario,
        perfil=perfil,
        total_usuarios=total_usuarios,
        total_logs=total_logs,
        total_topicos=total_topicos
    )

@app.route("/admin/historico", methods=["GET", "POST"])
def admin_historico():
    if not session.get("logado"):
        return redirect(url_for("login"))

    termo = request.args.get("q", "").strip()

    conn = get_db()
    if termo:
        cur = conn.execute("""
            SELECT * FROM historico
            WHERE pergunta LIKE ? OR resposta LIKE ?
            ORDER BY id DESC
            LIMIT 300
        """, (f"%{termo}%", f"%{termo}%"))
    else:
        cur = conn.execute("SELECT * FROM historico ORDER BY id DESC LIMIT 300")

    registros = cur.fetchall()
    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Histórico - Caminho de Anchieta</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family: Arial, sans-serif; background:#0b2a4a; }
.topo { background:white; padding:15px 20px; border-bottom:4px solid #d4a017; font-size:24px; font-weight:bold; color:#0b2a4a; }
.container { padding:20px; }
.box { background:white; padding:20px; border-radius:12px; max-width:1200px; margin:auto; box-shadow:0 4px 10px rgba(0,0,0,0.2); }

.filtros { display:flex; gap:10px; margin-bottom:15px; }
.filtros input { flex:1; padding:8px; }
button, .btn {
    padding:10px 16px; border-radius:8px; border:none; background:#d4a017;
    font-weight:bold; color:#0b2a4a; cursor:pointer; text-decoration:none;
}
.btn-sec { background:#ccc; color:#333; }

.item { border-bottom:1px solid #ddd; padding:10px 0; }
.data { font-size:12px; color:#666; }
.pergunta { font-weight:bold; color:#0b2a4a; }
.resposta { margin-top:5px; }

a.voltar { display:inline-block; margin-top:15px; font-weight:bold; color:#0b2a4a; text-decoration:none; }
</style>
</head>
<body>

<div class="topo">📜 Histórico de Perguntas e Respostas</div>

<div class="container">
  <div class="box">

    <form class="filtros" method="get">
      <input type="text" name="q" placeholder="Buscar por palavra..." value="{{ termo }}">
      <button type="submit">🔍 Buscar</button>
      <a class="btn btn-sec" href="/admin/historico">Limpar</a>
    </form>

    <div style="margin-bottom:10px;">
      <a class="btn" href="/admin/historico/limpar" onclick="return confirm('Tem certeza que deseja apagar TODO o histórico?');">🗑️ Apagar tudo</a>
    </div>

    {% for r in registros %}
      <div class="item">
        <div class="data">{{ r["data_hora"] }}</div>
        <div class="pergunta">❓ {{ r["pergunta"] }}</div>
        <div class="resposta">💬 {{ r["resposta"] }}</div>
      </div>
    {% else %}
      <p>Nenhum registro encontrado.</p>
    {% endfor %}

    <a class="voltar" href="/admin">⬅ Voltar ao painel</a>

  </div>
</div>

</body>
</html>
""", registros=registros, termo=termo)

@app.route("/admin/historico/limpar")
def limpar_historico():
    if not session.get("logado"):
        return redirect(url_for("login"))

    # opcional: só admin pode limpar
    if not tem_nivel("editor") and session.get("perfil") != "admin":
        return "Você não tem permissão para acessar esta página.", 403

    conn = get_db()
    conn.execute("DELETE FROM historico")
    conn.commit()
    conn.close()

    return redirect(url_for("admin_historico"))

@app.route("/admin/usuarios", methods=["GET", "POST"])
def admin_usuarios():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("admin"):
        return "Apenas administradores podem gerenciar usuários.", 403

    mensagem = ""

    if request.method == "POST":

        novo_usuario = request.form.get("usuario", "").strip()
        nova_senha = request.form.get("senha", "").strip()
        novo_perfil = request.form.get("perfil", "").strip()
        novas_permissoes = request.form.getlist("permissoes")
        permissoes_str = ",".join(novas_permissoes)

        if not novo_usuario or not nova_senha or not novo_perfil:
            mensagem = "Preencha todos os campos."
        else:
            try:
                conn = get_db()
                conn.execute(
                    """
                    INSERT INTO usuarios 
                    (usuario, senha_hash, perfil, permissoes, ativo, trocar_senha)
                    VALUES (?, ?, ?, ?, 1, 0)
                    """,
                    (
                        novo_usuario,
                        generate_password_hash(nova_senha),
                        novo_perfil,
                        permissoes_str
                    )
                )
                conn.commit()
                conn.close()

                registrar_log("Criou usuário", novo_usuario)

                mensagem = "Usuário criado com sucesso!"

            except sqlite3.IntegrityError:
                mensagem = "Esse usuário já existe."

    conn = get_db()
    cur = conn.execute("SELECT id, usuario, perfil, IFNULL(ativo,1) as ativo FROM usuarios ORDER BY usuario")
    usuarios = cur.fetchall()
    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Gerenciar Usuários</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family: Arial, sans-serif; background:#0b2a4a; }
.topo { background:white; padding:15px 20px; border-bottom:4px solid #d4a017; font-size:24px; font-weight:bold; color:#0b2a4a; }
.container { padding:20px; }
.box { background:white; padding:20px; border-radius:12px; max-width:1000px; margin:auto; }

table { width:100%; border-collapse:collapse; margin-top:20px; }
th, td { padding:8px; border-bottom:1px solid #ddd; text-align:left; }

input[type="text"],
input[type="password"],
select {
    padding:8px;
    margin:5px 0;
    width:100%;
}

input[type="checkbox"] {
    width:auto;
    margin-right:6px;
}
button { padding:10px 16px; border-radius:8px; border:none; background:#d4a017; font-weight:bold; color:#0b2a4a; cursor:pointer; }
.msg { margin-top:10px; font-weight:bold; color:green; }
.erro { margin-top:10px; font-weight:bold; color:red; }

a { display:inline-block; margin-top:15px; font-weight:bold; color:#0b2a4a; text-decoration:none; }
</style>
</head>
<body>

<div class="topo">👥 Gerenciar Usuários</div>

<div class="container">
<div class="box">

<h3>Criar novo usuário</h3>
<form method="post">
    <input type="text" name="usuario" placeholder="Usuário" required>
    <input type="password" name="senha" placeholder="Senha" required>
    <select name="perfil" required>
    <option value="">Selecione o perfil</option>
    <option value="admin">Admin</option>
    <option value="coordenador">Coordenador</option>
    <option value="editor">Editor</option>
    <option value="visualizador">Visualizador</option>
</select>

<br><br>
<label><b>Permissões adicionais</b></label><br>

<input type="checkbox" name="permissoes" value="editor"> Editor<br>
<input type="checkbox" name="permissoes" value="logs"> Logs<br>
<input type="checkbox" name="permissoes" value="usuarios"> Gerenciar Usuários<br><br>

<button type="submit">➕ Criar usuário</button>
</form>

{% if mensagem %}
<div class="msg">{{ mensagem }}</div>
{% endif %}

<h3>Usuários cadastrados</h3>

<table>
<tr>
    <th>Usuário</th>
    <th>Perfil</th>
    <th>Status</th>
    <th>Ações</th>
</tr>

{% for u in usuarios %}
<tr>
    <td>{{ u["usuario"] }}</td>
    <td>{{ u["perfil"] }}</td>
    <td>{{ "Ativo" if u["ativo"] == 1 else "Inativo" }}</td>
    <td>

        <a href="/admin/usuarios/editar?id={{ u['id'] }}">✏️ Editar</a> |

        {% if u["ativo"] == 1 %}
            <a href="/admin/usuarios/desativar?id={{ u['id'] }}">🚫 Desativar</a> |
        {% else %}
            <a href="/admin/usuarios/ativar?id={{ u['id'] }}">✅ Ativar</a> |
        {% endif %}

        <a href="/admin/usuarios/resetar?id={{ u['id'] }}">🔁 Resetar</a> |

        {% if u["usuario"] != "admin" %}
            <a href="/admin/usuarios/excluir/{{ u['id'] }}">🗑️ Excluir</a>
        {% endif %}

    </td>
</tr>
{% endfor %}
</table>

<a href="/admin">⬅ Voltar ao painel</a>

</div>
</div>

</body>
</html>
""", usuarios=usuarios, mensagem=mensagem)

@app.route("/admin/usuarios/excluir/<int:user_id>")
def excluir_usuario(user_id):
    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("admin"):
        return "Apenas administradores podem excluir usuários.", 403

    conn = get_db()

    cur = conn.execute("SELECT usuario FROM usuarios WHERE id=?", (user_id,))
    u = cur.fetchone()

    if u and u["usuario"] == "admin":
        conn.close()
        return "Não é permitido excluir o usuário admin."

    conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    registrar_log("Excluiu usuário", f"usuario_id={user_id}")

    return redirect(url_for("admin_usuarios"))

@app.route("/admin/usuarios/desativar")
def admin_usuarios_desativar():
    if not session.get("logado"):
        return redirect(url_for("login"))
    if not tem_nivel("admin"):
        return "Apenas administradores podem alterar usuários.", 403

    uid = request.args.get("id")
    if not uid:
        return redirect(url_for("admin_usuarios"))

    conn = get_db()
    conn.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (uid,))
    conn.commit()
    conn.close()

    registrar_log("Desativou usuário", f"usuario_id={uid}")

    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/ativar")
def admin_usuarios_ativar():
    if not session.get("logado"):
        return redirect(url_for("login"))
    if not tem_nivel("admin"):
        return "Apenas administradores podem alterar usuários.", 403

    uid = request.args.get("id")
    if not uid:
        return redirect(url_for("admin_usuarios"))

    conn = get_db()
    conn.execute("UPDATE usuarios SET ativo=1 WHERE id=?", (uid,))
    conn.commit()
    conn.close()

    registrar_log("Ativou usuário", f"usuario_id={uid}")

    return redirect(url_for("admin_usuarios"))

@app.route("/admin/usuarios/resetar")
def admin_usuarios_resetar():
    if not session.get("logado"):
        return redirect(url_for("login"))
    if not tem_nivel("admin"):
        return "Apenas administradores podem alterar usuários.", 403
    uid = request.args.get("id")
    if not uid:
        return redirect(url_for("admin_usuarios"))

    # senha padrão (você pode mudar depois)
    nova_senha = "1234"

    conn = get_db()
    conn.execute(
        "UPDATE usuarios SET senha_hash=?, trocar_senha=1 WHERE id=?",
        (generate_password_hash(nova_senha), uid)
    )
    conn.commit()
    conn.close()

    registrar_log("Resetou senha", f"usuario_id={uid}")

    return redirect(url_for("admin_usuarios"))

@app.route("/admin/logs")
def admin_logs():
    if not session.get("logado"):
        return redirect(url_for("login"))
    if not tem_nivel("coordenador"):
        return "Você não tem permissão para ver os logs.", 403

    conn = get_db()
    cur = conn.execute("SELECT * FROM logs_admin ORDER BY id DESC LIMIT 500")
    logs = cur.fetchall()
    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Logs Administrativos</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family: Arial, sans-serif; background:#0b2a4a; }
.topo { background:white; padding:15px 20px; border-bottom:4px solid #d4a017; font-size:24px; font-weight:bold; color:#0b2a4a; }
.container { padding:20px; }
.box { background:white; padding:20px; border-radius:12px; max-width:1100px; margin:auto; box-shadow:0 4px 10px rgba(0,0,0,0.2); }
table { width:100%; border-collapse: collapse; }
th, td { padding:8px; border-bottom:1px solid #ddd; text-align:left; }
a.voltar { display:inline-block; margin-top:15px; font-weight:bold; color:#0b2a4a; text-decoration:none; }
</style>
</head>
<body>

<div class="topo">🧾 Logs Administrativos</div>

<div class="container">
  <div class="box">
    <table>
      <tr><th>Data/Hora</th><th>Admin</th><th>Ação</th><th>Alvo</th></tr>
      {% for l in logs %}
      <tr>
        <td>{{ l["data_hora"] }}</td>
        <td>{{ l["usuario_admin"] }}</td>
        <td>{{ l["acao"] }}</td>
        <td>{{ l["alvo"] }}</td>
      </tr>
      {% endfor %}
    </table>

    <a class="voltar" href="/admin">⬅ Voltar ao painel</a>
  </div>
</div>

</body>
</html>
""", logs=logs)

@app.route("/admin/usuarios/editar", methods=["GET", "POST"])
def admin_usuarios_editar():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("admin"):
        return "Apenas administradores podem editar usuários.", 403

    uid = request.args.get("id")
    if not uid:
        return redirect(url_for("admin_usuarios"))

    conn = get_db()

    # 🔍 Busca usuário
    cur = conn.execute("""
        SELECT id, usuario, perfil,
        IFNULL(ativo,1) as ativo,
        IFNULL(permissoes,'') as permissoes
        FROM usuarios
        WHERE id=?
    """, (uid,))
    
    usuario = cur.fetchone()

    if not usuario:
        conn.close()
        return redirect(url_for("admin_usuarios"))

    # 🔽 BUSCA CATEGORIAS DIRETO DO BANCO (SUBSTITUI SECOES)
    cur = conn.execute("SELECT id, nome FROM secoes ORDER BY nome")
    secoes = cur.fetchall()

    if request.method == "POST":

        novo_usuario = request.form.get("usuario", "").strip()
        nova_senha = request.form.get("senha", "").strip()
        novo_perfil = request.form.get("perfil", "").strip()
        novas_permissoes = request.form.getlist("permissoes")
        permissoes_str = ",".join(novas_permissoes)

        if not novo_usuario or not novo_perfil:
            conn.close()
            return "Usuário e perfil são obrigatórios."

        if nova_senha:
            conn.execute("""
                UPDATE usuarios 
                SET usuario=?, perfil=?, senha_hash=?, permissoes=?
                WHERE id=?
            """, (
                novo_usuario,
                novo_perfil,
                generate_password_hash(nova_senha),
                permissoes_str,
                uid
            ))
        else:
            conn.execute("""
                UPDATE usuarios 
                SET usuario=?, perfil=?, permissoes=?
                WHERE id=?
            """, (
                novo_usuario,
                novo_perfil,
                permissoes_str,
                uid
            ))

        conn.commit()
        conn.close()

        registrar_log("Editou usuário", f"usuario_id={uid}")

        return redirect(url_for("admin_usuarios"))

    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Editar Usuário</title>
<style>
body { font-family: Arial; background:#0b2a4a; margin:0; }
.topo { background:white; padding:15px; font-size:24px; font-weight:bold; color:#0b2a4a; }
.container { padding:20px; }
.box { background:white; padding:20px; border-radius:12px; max-width:600px; margin:auto; }

input, select { padding:8px; margin:6px 0; width:100%; }
input[type="checkbox"] { width:auto; margin-right:6px; }

button {
    padding:10px 16px;
    border-radius:8px;
    border:none;
    background:#d4a017;
    font-weight:bold;
    color:#0b2a4a;
    cursor:pointer;
}

a { display:inline-block; margin-top:15px; font-weight:bold; color:#0b2a4a; text-decoration:none; }

.secao-box { margin-left:15px; }
</style>
</head>
<body>

<div class="topo">✏️ Editar Usuário</div>

<div class="container">
<div class="box">

<form method="post">

<label>Usuário</label>
<input type="text" name="usuario" value="{{ usuario['usuario'] }}">

<label>Perfil</label>
<select name="perfil">
    <option value="admin" {{ "selected" if usuario["perfil"]=="admin" else "" }}>Admin</option>
    <option value="coordenador" {{ "selected" if usuario["perfil"]=="coordenador" else "" }}>Coordenador</option>
    <option value="editor" {{ "selected" if usuario["perfil"]=="editor" else "" }}>Editor</option>
    <option value="visualizador" {{ "selected" if usuario["perfil"]=="visualizador" else "" }}>Visualizador</option>
</select>

<br>
<label><b>Permissões Gerais</b></label><br><br>

<label>
<input type="checkbox" name="permissoes" value="editor"
{% if "editor" in usuario["permissoes"] %}checked{% endif %}>
Editor
</label><br>

<label>
<input type="checkbox" name="permissoes" value="logs"
{% if "logs" in usuario["permissoes"] %}checked{% endif %}>
Logs
</label><br>

<label>
<input type="checkbox" name="permissoes" value="usuarios"
{% if "usuarios" in usuario["permissoes"] %}checked{% endif %}>
Gerenciar Usuários
</label><br><br>

<label><b>Seções que pode editar</b></label><br><br>

<div class="secao-box">
{% for sec in secoes %}
<label>
<input type="checkbox" name="permissoes" value="{{ sec['nome'] }}"
{% if sec['nome'] in usuario["permissoes"] %}checked{% endif %}>
{{ sec['nome'].replace("_"," ").title() }}
</label><br>
{% endfor %}
</div>

<br>

<label>Nova senha (deixe em branco para não alterar)</label>
<input type="password" name="senha" placeholder="Nova senha opcional">

<button type="submit">💾 Salvar alterações</button>

</form>

<a href="/admin/usuarios">⬅ Voltar</a>

</div>
</div>

</body>
</html>
""", usuario=usuario, secoes=secoes)

@app.route("/admin/aprendizado")
def admin_aprendizado():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("coordenador"):
        return "Você não tem permissão para acessar o aprendizado.", 403

    conn = get_db()
    cur = conn.execute("""
        SELECT * FROM aprendizado
        ORDER BY contador DESC
    """)
    registros = cur.fetchall()
    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Aprendizado Automático</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; font-family: Arial; background:#0b2a4a; }
.topo { background:white; padding:15px; border-bottom:4px solid #d4a017; font-size:24px; font-weight:bold; color:#0b2a4a; }
.container { padding:20px; }
.box { background:white; padding:20px; border-radius:12px; max-width:1100px; margin:auto; box-shadow:0 4px 10px rgba(0,0,0,0.2); }

table { width:100%; border-collapse: collapse; }
th, td { padding:10px; border-bottom:1px solid #ddd; text-align:left; }

th { background:#f5f5f5; }

button {
    padding:6px 10px;
    border-radius:6px;
    border:none;
    background:#d4a017;
    font-weight:bold;
    color:#0b2a4a;
    cursor:pointer;
}

.btn-danger {
    background:#c0392b;
    color:white;
}

.voltar {
    display:inline-block;
    margin-top:15px;
    font-weight:bold;
    color:#0b2a4a;
    text-decoration:none;
}
</style>
</head>
<body>

<div class="topo">🧠 Aprendizado Automático</div>

<div class="container">
<div class="box">

<table>
<tr>
<th>Pergunta</th>
<th>Qtd</th>
<th>Ações</th>
</tr>

{% for r in registros %}
<tr>
<td>{{ r["pergunta"] }}</td>
<td>{{ r["contador"] }}</td>
<td>

<a href="/admin/aprendizado/converter/{{ r['id'] }}">
<button>Converter</button>
</a>

<a href="/admin/aprendizado/excluir/{{ r['id'] }}">
<button class="btn-danger">Excluir</button>
</a>

</td>
</tr>
{% else %}
<tr>
<td colspan="3">Nenhuma pergunta registrada ainda.</td>
</tr>
{% endfor %}
</table>

<br>

<a href="/admin/aprendizado/limpar">
<button class="btn-danger">🗑️ Limpar Tudo</button>
</a>

<br><br>

<a class="voltar" href="/admin">⬅ Voltar ao painel</a>

</div>
</div>

</body>
</html>
""", registros=registros)

@app.route("/admin/aprendizado/excluir/<int:id>")
def excluir_aprendizado(id):

    if not session.get("logado"):
        return redirect(url_for("login"))

    conn = get_db()
    conn.execute("DELETE FROM aprendizado WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect(url_for("admin_aprendizado"))

@app.route("/admin/aprendizado/converter/<int:id>", methods=["GET", "POST"])
def converter_aprendizado(id):

    if not session.get("logado"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.execute("SELECT * FROM aprendizado WHERE id=?", (id,))
    registro = cur.fetchone()

    if not registro:
        conn.close()
        return redirect(url_for("admin_aprendizado"))

    pergunta = registro["pergunta"]
    sugestao_palavras = sugerir_palavras_chave(pergunta)
    resposta_sugerida = sugerir_resposta(pergunta)

    # 🔽 BUSCA CATEGORIAS DIRETO DO BANCO
    cur = conn.execute("SELECT id, nome FROM secoes ORDER BY nome")
    secoes = cur.fetchall()

    if request.method == "POST":

        secao_id = request.form.get("secao")  # corrigido
        palavras_chave = request.form.get("palavras", "").strip()
        resposta = request.form.get("resposta", "").strip()

        if not secao_id or not palavras_chave or not resposta:  # corrigido
            conn.close()
            return "Preencha todos os campos"

        # 🔥 GERA NOME AUTOMÁTICO DO TÓPICO
        nome_topico = palavras_chave.split(",")[0].strip().upper()
        nome_topico = nome_topico.replace(" ", "_")
        nome_topico = re.sub(r"[^A-Z0-9_]", "", nome_topico)

        conn.execute("""
            INSERT INTO topicos (secao_id, titulo, palavras_chave, resposta)
            VALUES (?, ?, ?, ?)
        """, (
            secao_id,
            nome_topico,
            palavras_chave,
            resposta
        ))

        # Remove do aprendizado
        conn.execute("DELETE FROM aprendizado WHERE id=?", (id,))
        conn.commit()
        conn.close()

        # 🔁 RECARREGA BASE DA IA
        global base
        base = carregar_base()

        return redirect(url_for("admin_topicos"))

    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Converter Pergunta</title>
<style>
body { font-family: Arial; background:#0b2a4a; margin:0; }
.topo { background:white; padding:15px; font-size:24px; font-weight:bold; color:#0b2a4a; }
.container { padding:20px; }
.box { background:white; padding:20px; border-radius:12px; max-width:800px; margin:auto; }
textarea, select { width:100%; margin:10px 0; padding:8px; }
button {
    padding:10px 16px;
    border-radius:8px;
    border:none;
    background:#d4a017;
    font-weight:bold;
    color:#0b2a4a;
    cursor:pointer;
}
</style>
</head>
<body>

<div class="topo">🧠 Converter Pergunta em Tópico</div>

<div class="container">
<div class="box">

<p><b>Pergunta original:</b></p>
<p>{{ pergunta }}</p>

<form method="post">

<label>Seção:</label>
<select name="secao">
{% for s in secoes %}
<option value="{{ s['id'] }}">{{ s['nome'].replace("_"," ").title() }}</option>
{% endfor %}
</select>

<label>Palavras-chave (separadas por vírgula):</label>
<textarea name="palavras" rows="3" required>{{ sugestao_palavras }}</textarea>

<label>Resposta que aparecerá no chat:</label>
<textarea name="resposta" rows="6" required>{{ resposta_sugerida }}</textarea>

<button type="submit">Salvar como novo tópico</button>

</form>

</div>
</div>

</body>
</html>
""", pergunta=pergunta, secoes=secoes, sugestao_palavras=sugestao_palavras,
    resposta_sugerida=resposta_sugerida)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin/aprendizado/limpar")
def limpar_aprendizado():

    if not session.get("logado"):
        return redirect(url_for("login"))

    conn = get_db()
    conn.execute("DELETE FROM aprendizado")
    conn.commit()
    conn.close()

    return redirect(url_for("admin_aprendizado"))

@app.route("/admin/topicos")
def admin_topicos():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("editor"):
        return "Você não tem permissão para acessar tópicos.", 403

    secao_filtro = request.args.get("secao", "")

    conn = get_db()

    # 🔽 Busca todas as seções
    cur = conn.execute("SELECT * FROM secoes ORDER BY nome")
    secoes = cur.fetchall()

    # 🔽 Busca tópicos com JOIN
    if secao_filtro:
        cur = conn.execute("""
            SELECT t.*, s.nome as secao_nome
            FROM topicos t
            JOIN secoes s ON t.secao_id = s.id
            WHERE s.id=?
            ORDER BY t.titulo
        """, (secao_filtro,))
    else:
        cur = conn.execute("""
            SELECT t.*, s.nome as secao_nome
            FROM topicos t
            JOIN secoes s ON t.secao_id = s.id
            ORDER BY s.nome, t.titulo
        """)

    topicos = cur.fetchall()
    conn.close()

    return render_template_string("""
    <html>
    <head>
    <title>Gerenciar Tópicos</title>
    <style>
    body { font-family: Arial; background:#0b2a4a; margin:0; }
    .box { background:white; padding:20px; margin:20px; border-radius:10px; }
    table { width:100%; border-collapse: collapse; }
    th, td { padding:10px; border-bottom:1px solid #ddd; }
    select { padding:6px; }
    button { padding:6px 10px; background:#d4a017; border:none; font-weight:bold; }
    a { text-decoration:none; }
    </style>
    </head>
    <body>

    <div class="box">
    <h2>Gerenciar Tópicos</h2>

    <form method="get">
        <label>Filtrar por Seção:</label>
        <select name="secao" onchange="this.form.submit()">
            <option value="">Todas</option>
            {% for s in secoes %}
                <option value="{{ s['id'] }}" {% if secao_filtro == s['id']|string %}selected{% endif %}>
                    {{ s['nome'].title() }}
                </option>
            {% endfor %}
        </select>
    </form>

    <br>
    <a href="/admin/topicos/novo"><button>Novo Tópico</button></a>
    <a href="/admin/secoes"><button>Criar Seção</button></a>
    <br><br>

    <table>
        <tr>
            <th>Seção</th>
            <th>Título</th>
            <th>Ações</th>
        </tr>

        {% for t in topicos %}
        <tr>
            <td>{{ t["secao_nome"] }}</td>
            <td>{{ t["titulo"] }}</td>
            <td>
                {% if session['perfil'] == 'admin' or t['secao_nome'].lower() in session.get('permissoes','').lower() %}
                <a href="/admin/topicos/editar/{{ t['id'] }}"><button>Editar</button></a>
                {% endif %}
                <a href="/admin/topicos/excluir/{{ t['id'] }}"><button>Excluir</button></a>
            </td>
        </tr>
        {% endfor %}
    </table>

    <br>
    <a href="/admin">Voltar</a>

    </div>
    </body>
    </html>
    """,
    topicos=topicos,
    secoes=secoes,
    secao_filtro=str(secao_filtro)
    )

@app.route("/admin/topicos/editar/<int:id>", methods=["GET", "POST"])
def editar_topico(id):

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("editor"):
        return "Você não tem permissão para editar tópicos.", 403

    # ✅ cria conexão primeiro
    conn = get_db()

    # 🔎 verifica a seção do tópico
    cur = conn.execute("""
        SELECT s.nome
        FROM topicos t
        JOIN secoes s ON t.secao_id = s.id
        WHERE t.id=?
    """, (id,))
    secao = cur.fetchone()

    if secao and not pode_editar_secao(secao["nome"]):
        conn.close()
        return "Você não tem permissão para editar esta seção.", 403

    # 🔽 busca todas as seções
    cur = conn.execute("SELECT * FROM secoes ORDER BY nome")
    secoes = cur.fetchall()

    # 🔽 busca tópico atual
    cur = conn.execute("""
        SELECT * FROM topicos
        WHERE id=?
    """, (id,))
    topico = cur.fetchone()

    if not topico:
        conn.close()
        return redirect("/admin/topicos")

    if request.method == "POST":

        secao_id = request.form.get("secao_id")
        titulo = request.form.get("titulo", "").strip()
        palavras = request.form.get("palavras", "").strip()
        resposta = request.form.get("resposta", "").strip()

        if not secao_id or not titulo or not palavras or not resposta:
            conn.close()
            return "Preencha todos os campos"

        conn.execute("""
            UPDATE topicos
            SET secao_id=?, titulo=?, palavras_chave=?, resposta=?
            WHERE id=?
        """, (secao_id, titulo, palavras, resposta, id))

        conn.commit()
        conn.close()

        # 🔄 recarrega base da IA
        global base
        base = carregar_base()

        return redirect("/admin/topicos")

    conn.close()

    return render_template_string("""
    <html>
    <head>
    <title>Editar Tópico</title>
    <style>
    body { font-family: Arial; background:#0b2a4a; margin:0; }
    .box { background:white; padding:20px; margin:20px; border-radius:10px; max-width:800px; }
    input, textarea, select { width:100%; padding:8px; margin:8px 0; }
    textarea { height:120px; }
    button { padding:8px 14px; background:#d4a017; border:none; font-weight:bold; }
    </style>
    </head>
    <body>

    <div class="box">
    <h2>Editar Tópico</h2>

    <form method="post">

    <label>Seção</label>
    <select name="secao_id" required>
    {% for s in secoes %}
    <option value="{{ s['id'] }}" {% if s['id'] == topico['secao_id'] %}selected{% endif %}>
    {{ s['nome'].title() }}
    </option>
    {% endfor %}
    </select>

    <label>Título</label>
    <input type="text" name="titulo" value="{{ topico['titulo'] }}" required>

    <label>Palavras-chave (separadas por vírgula)</label>
    <textarea name="palavras" required>{{ topico['palavras_chave'] }}</textarea>

    <label>Resposta</label>
    <textarea name="resposta" required>{{ topico['resposta'] }}</textarea>

    <button type="submit">Salvar Alterações</button>

    </form>

    <br>
    <a href="/admin/topicos">Voltar</a>

    </div>

    </body>
    </html>
    """, topico=topico, secoes=secoes)

@app.route("/admin/topicos/novo", methods=["GET", "POST"])
def novo_topico():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("editor"):
        return "Você não tem permissão para criar tópicos.", 403

    conn = get_db()

    # 🔽 Busca todas as seções para o select
    cur = conn.execute("SELECT * FROM secoes ORDER BY nome")
    secoes = cur.fetchall()

    if request.method == "POST":

        secao_id = request.form.get("secao_id")
        titulo = request.form.get("titulo", "").strip()
        palavras = request.form.get("palavras", "").strip()
        resposta = request.form.get("resposta", "").strip()

        if not secao_id or not titulo or not palavras or not resposta:
            conn.close()
            return "Preencha todos os campos"

        conn.execute("""
            INSERT INTO topicos (secao_id, titulo, palavras_chave, resposta)
            VALUES (?, ?, ?, ?)
        """, (secao_id, titulo, palavras, resposta))

        conn.commit()
        conn.close()

        # 🔥 recarrega a base da IA
        global base
        base = carregar_base()

        return redirect("/admin/topicos")

    conn.close()

    return render_template_string("""
    <html>
    <head>
    <title>Novo Tópico</title>
    <style>
    body { font-family: Arial; background:#0b2a4a; margin:0; }
    .box { background:white; padding:20px; margin:20px; border-radius:10px; max-width:800px; }
    input, textarea, select { width:100%; padding:8px; margin:8px 0; }
    textarea { height:120px; }
    button { padding:8px 14px; background:#d4a017; border:none; font-weight:bold; }
    </style>
    </head>
    <body>

    <div class="box">
    <h2>Novo Tópico</h2>

    <form method="post">

        <label>Seção</label>
        <select name="secao_id" required>
            <option value="">Selecione</option>
            {% for s in secoes %}
                <option value="{{ s['id'] }}">
                    {{ s['nome'].title() }}
                </option>
            {% endfor %}
        </select>

        <label>Título</label>
        <input type="text" name="titulo" required>

        <label>Palavras-chave (separadas por vírgula)</label>
        <textarea name="palavras" required></textarea>

        <label>Resposta que aparecerá no chat</label>
        <textarea name="resposta" required></textarea>

        <button type="submit">Salvar Tópico</button>

    </form>

    <br>
    <a href="/admin/topicos">Voltar</a>

    </div>
    </body>
    </html>
    """, secoes=secoes)

@app.route("/admin/secoes", methods=["GET", "POST"])
def admin_secoes():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("coordenador"):
        return "Você não tem permissão para gerenciar seções.", 403

    conn = get_db()

    # 🔹 Criar nova seção
    if request.method == "POST":
        nome = request.form.get("nome", "").strip().lower()

        if nome:
            try:
                conn.execute("INSERT INTO secoes (nome) VALUES (?)", (nome,))
                conn.commit()
            except sqlite3.IntegrityError:
                pass

    # 🔹 Buscar seções + contador de tópicos
    cur = conn.execute("""
        SELECT s.id, s.nome,
        COUNT(t.id) as total_topicos
        FROM secoes s
        LEFT JOIN topicos t ON t.secao_id = s.id
        GROUP BY s.id
        ORDER BY s.nome
    """)
    secoes = cur.fetchall()
    conn.close()

    return render_template_string("""
    <html>
    <head>
    <title>Gerenciar Seções</title>
    <style>
    body { font-family: Arial; background:#0b2a4a; margin:0; }
    .box { background:white; padding:20px; margin:20px; border-radius:10px; }
    table { width:100%; border-collapse: collapse; margin-top:20px; }
    th, td { padding:10px; border-bottom:1px solid #ddd; }
    input { padding:8px; }
    button { padding:6px 10px; background:#d4a017; border:none; font-weight:bold; }
    .danger { background:#c0392b; color:white; }
    </style>
    </head>
    <body>

    <div class="box">
    <h2>Gerenciar Seções</h2>

    <form method="post">
        <input type="text" name="nome" placeholder="Nova seção (ex: liturgia)" required>
        <button type="submit">Criar</button>
    </form>

    <table>
    <tr>
        <th>Seção</th>
        <th>Tópicos</th>
        <th>Ações</th>
    </tr>

    {% for s in secoes %}
    <tr>
        <td>{{ s["nome"] }}</td>
        <td>{{ s["total_topicos"] }}</td>
        <td>
            <a href="/admin/secoes/excluir/{{ s['id'] }}">
                <button class="danger">Excluir</button>
            </a>
        </td>
    </tr>
    {% endfor %}
    </table>

    <br>
    <a href="/admin">Voltar</a>

    </div>
    </body>
    </html>
    """, secoes=secoes)

@app.route("/admin/secoes/excluir/<int:id>")
def excluir_secao(id):

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("coordenador"):
        return "Você não tem permissão para excluir seções.", 403

    conn = get_db()

    # 🔹 Verifica se tem tópicos
    cur = conn.execute("SELECT COUNT(*) as total FROM topicos WHERE secao_id=?", (id,))
    total = cur.fetchone()["total"]

    if total > 0:
        conn.close()
        return "Não é possível excluir uma seção que possui tópicos."

    conn.execute("DELETE FROM secoes WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect("/admin/secoes")

@app.route("/admin/topicos/excluir/<int:id>")
def excluir_topico(id):

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("editor"):
        return "Você não tem permissão para excluir tópicos.", 403

    conn = get_db()

    # 🔎 verifica a seção do tópico
    cur = conn.execute("""
        SELECT s.nome
        FROM topicos t
        JOIN secoes s ON t.secao_id = s.id
        WHERE t.id=?
    """, (id,))
    secao = cur.fetchone()

    if not secao:
        conn.close()
        return redirect("/admin/topicos")

    # 🔒 verifica permissão da seção
    if not pode_editar_secao(secao["nome"]):
        conn.close()
        return "Você não tem permissão para excluir tópicos desta seção.", 403

    # 🗑 exclui tópico
    conn.execute("DELETE FROM topicos WHERE id=?", (id,))
    conn.commit()
    conn.close()

    # 🔄 recarrega base da IA
    global base
    base = carregar_base()

    return redirect("/admin/topicos")

@app.route("/admin/radar")
def admin_radar():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("coordenador"):
        return "Sem permissão"

    perguntas = perguntas_importantes()

    return render_template_string("""
<html>
<head>
<title>Radar Pastoral</title>
<style>
body { font-family: Arial; background:#0b2a4a; margin:0; }

.box {
background:white;
padding:20px;
margin:20px;
border-radius:10px;
}

table {
width:100%;
border-collapse:collapse;
}

th,td{
padding:10px;
border-bottom:1px solid #ddd;
}

button{
padding:6px 10px;
background:#d4a017;
border:none;
font-weight:bold;
}

</style>
</head>

<body>

<div class="box">

<h2>📊 Radar Pastoral</h2>

<table>

<tr>
<th>Pergunta</th>
<th>Quantidade</th>
<th>Ação</th>
</tr>

{% for p in perguntas %}

<tr>
<td>{{ p["pergunta"] }}</td>
<td>{{ p["contador"] }}</td>

<td>
<a href="/admin/aprendizado">
<button>Ver aprendizado</button>
</a>
</td>

</tr>

{% endfor %}

</table>

<br>

<a href="/admin">Voltar</a>

</div>

</body>
</html>
""", perguntas=perguntas)

@app.route("/admin/perguntas_criticas")
def admin_perguntas_criticas():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("coordenador"):
        return "Sem permissão"

    perguntas = perguntas_criticas()

    return render_template_string("""
<html>
<head>
<title>Perguntas Importantes</title>

<style>
body { font-family: Arial; background:#0b2a4a; margin:0; }

.box{
background:white;
padding:20px;
margin:20px;
border-radius:10px;
}

table{
width:100%;
border-collapse:collapse;
}

th,td{
padding:10px;
border-bottom:1px solid #ddd;
}

button{
padding:6px 10px;
background:#d4a017;
border:none;
font-weight:bold;
}

</style>
</head>

<body>

<div class="box">

<h2>🔥 Perguntas Importantes da Comunidade</h2>

<table>

<tr>
<th>Pergunta</th>
<th>Repetições</th>
<th>Ação</th>
</tr>

{% for p in perguntas %}

<tr>

<td>{{ p["pergunta"] }}</td>
<td>{{ p["contador"] }}</td>

<td>

<a href="/admin/aprendizado/converter/{{ p['id'] }}">
<button>Criar tópico</button>
</a>

</td>

</tr>

{% endfor %}

</table>

<br>

<a href="/admin">Voltar</a>

</div>

</body>
</html>
""", perguntas=perguntas)

@app.route("/admin/backup")
def admin_backup():

    if not session.get("logado"):
        return redirect(url_for("login"))

    if not tem_nivel("admin"):
        return "Apenas admin pode fazer backup."

    backup_banco()

    return "Backup criado com sucesso!"

# ---------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)