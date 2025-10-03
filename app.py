from flask import Flask, render_template, request
import requests
import re
import pyodbc
from langchain_community.utilities import SQLDatabase

app = Flask(__name__)

# --- Configuration ---
GOOGLE_API_KEY = "AIzaSyCk92cOovyZprgOvNuB0fyXeBhoCXSebGM"

# Configuration SQL Server
def create_db_connection():
    """Crée une connexion directe à la base de données SQL Server"""
    try:
        connection_string = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=v2devsqlserver.database.windows.net,1433;"
            "DATABASE=v2dev;"
            "UID=dbRead;"
            "PWD=Domino00%;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=30;"
        )
        return pyodbc.connect(connection_string)
    except Exception as e:
        print(f"Erreur de connexion: {e}")
        return None

def get_db_schema():
    """Récupère le schéma de la base de données (version optimisée)"""
    conn = create_db_connection()
    if not conn:
        return "Erreur de connexion à la base de données"
    
    try:
        cursor = conn.cursor()
        
        # Récupérer la liste des tables principales
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
            AND TABLE_NAME IN (
                'Contracts', 'Persons', 'JuridicalEntities', 'Projects', 
                'Appointments', 'Tasks', 'Notes', 'Echeances', 'Products',
                'Collaborators', 'Companies', 'Cities', 'Departments'
            )
            ORDER BY TABLE_NAME
        """)
        tables = cursor.fetchall()
        
        schema_info = "=== STRUCTURE DE LA BASE DE DONNÉES ===\n\n"
        
        for table in tables:
            table_name = table[0]
            schema_info += f"📋 TABLE: {table_name}\n"
            
            # Récupérer les colonnes principales de chaque table
            cursor.execute(f"""
                SELECT TOP 10
                    COLUMN_NAME,
                    DATA_TYPE,
                    IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = '{table_name}'
                ORDER BY ORDINAL_POSITION
            """)
            columns = cursor.fetchall()
            
            # Limiter à 10 colonnes principales par table
            for i, col in enumerate(columns[:10]):
                col_name, data_type, nullable = col
                null_info = "NULL" if nullable == "YES" else "NOT NULL"
                schema_info += f"  - {col_name}: {data_type} {null_info}\n"
            
            if len(columns) > 10:
                schema_info += f"  ... et {len(columns) - 10} autres colonnes\n"
            
            schema_info += "\n"
        
        conn.close()
        return schema_info
        
    except Exception as e:
        conn.close()
        return f"Erreur lors de la récupération du schéma: {e}"

def execute_query(query):
    """Exécute une requête SQL et retourne les résultats"""
    conn = create_db_connection()
    if not conn:
        return "Erreur de connexion à la base de données"
    
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        
        # Récupérer les noms des colonnes
        columns = [column[0] for column in cursor.description] if cursor.description else []
        
        # Récupérer les données
        rows = cursor.fetchall()
        
        conn.close()
        
        return {
            'columns': columns,
            'rows': rows,
            'count': len(rows)
        }
        
    except Exception as e:
        conn.close()
        return f"Erreur lors de l'exécution de la requête: {e}"

# Initialisation
print("🔄 Initialisation de la connexion à SQL Server...")
conn = create_db_connection()
if conn:
    print("✅ Connexion SQL Server réussie!")
    conn.close()
else:
    print("❌ Échec de la connexion SQL Server")

# --- Gemini 2.0 Flash API ---
def ask_gemini_sql(question, schema_description):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}"

    prompt = f"""Tu es un assistant SQL expert pour SQL Server.
Ta tâche est de transformer une question utilisateur en requête SQL lisible par une base de données SQL Server.

Voici la structure des tables disponibles :
{schema_description}

Voici la question utilisateur :
{question}

IMPORTANT:
- Utilise uniquement la syntaxe SQL Server (T-SQL)
- Utilise les noms de tables et colonnes exacts du schéma fourni
- Assure-toi que la requête est valide et sécurisée
- Limite les résultats à 100 lignes maximum avec TOP 100 si nécessaire
- Utilise des noms de colonnes explicites dans SELECT

Retourne uniquement la requête SQL entre balises <sql>...</sql>, sans aucune explication.
"""

    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()

        content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        match = re.search(r"<sql>(.*?)</sql>", content, re.DOTALL)
        return match.group(1).strip() if match else content
    except Exception as e:
        return f"Erreur lors de la génération SQL: {e}"

def clean_sql_code(code):
    """Nettoie le code SQL généré par Gemini"""
    # Supprimer les backticks markdown
    cleaned = code.strip().removeprefix("```sql").removesuffix("```").strip()
    # Supprimer les backticks restants
    cleaned = cleaned.replace("`", "")
    return cleaned

# --- Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    result = ""
    sql_query = ""
    error = ""
    columns = []
    row_count = 0
    
    if request.method == "POST":
        question = request.form["question"]
        try:
            # Récupérer le schéma de la base de données
            schema = get_db_schema()
            if "Erreur" in schema:
                error = schema
            else:
                # Générer la requête SQL avec Gemini
                raw_sql = ask_gemini_sql(question, schema)
                sql_query = clean_sql_code(raw_sql)
                
                # Exécuter la requête
                query_result = execute_query(sql_query)
                
                if isinstance(query_result, dict):
                    result = query_result['rows']
                    columns = query_result['columns']
                    row_count = query_result['count']
                else:
                    error = query_result
                    
        except Exception as e:
            error = str(e)
    
    return render_template("index.html", 
                         result=result, 
                         sql_query=sql_query, 
                         error=error,
                         columns=columns,
                         row_count=row_count)

@app.route("/schema")
def schema():
    """Route pour afficher le schéma de la base de données"""
    schema = get_db_schema()
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Schéma BDD - Vetoptim SQL Assistant</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                min-height: 100vh;
                padding: 20px;
                margin: 0;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }}
            .logo {{
                width: 80px;
                height: auto;
                margin-bottom: 15px;
            }}
            .header h1 {{
                font-size: 2.2em;
                margin-bottom: 10px;
                font-weight: 700;
                color: white;
            }}
            .content {{
                padding: 40px;
            }}
            .nav-link {{
                display: inline-block;
                background: rgba(255, 255, 255, 0.9);
                color: #1e3a8a;
                padding: 10px 20px;
                border-radius: 20px;
                text-decoration: none;
                transition: all 0.3s ease;
                margin: 10px;
                font-weight: 600;
            }}
            .nav-link:hover {{
                background: #f59e0b;
                color: white;
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(245, 158, 11, 0.3);
            }}
            pre {{
                background: #1e293b;
                color: #e2e8f0;
                padding: 20px;
                border-radius: 10px;
                overflow-x: auto;
                font-family: 'Fira Code', 'Courier New', monospace;
                font-size: 14px;
                line-height: 1.6;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                border-left: 4px solid #3b82f6;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img src="/static/image.png" alt="Vetoptim Logo" class="logo">
                <h1>📋 Schéma de la Base de Données</h1>
                <a href="/" class="nav-link">🏠 Retour à l'accueil</a>
                <a href="/diagram" class="nav-link">🗺️ Voir le diagramme</a>
            </div>
            <div class="content">
                <pre>{schema}</pre>
            </div>
        </div>
    </body>
    </html>
    """

@app.route("/diagram")
def diagram():
    """Route pour afficher le diagramme de la base de données"""
    mermaid_code = """
erDiagram
    PERSONS {
        uniqueidentifier PersonId PK
        varchar PersonType
        nvarchar Email
        nvarchar FirstName
        nvarchar LastName
        varchar Mobile
        varchar Phone
        date BirthDate
    }

    JURIDICALENTITIES {
        uniqueidentifier JuridicalEntityId PK
        nvarchar JuridicalEntityType
        nvarchar Siret
        nvarchar Siren
        bit IsCustomer
        nvarchar CompanyName
    }

    CONTRACTS {
        uniqueidentifier ContractId PK
        nvarchar StatusCode
        nvarchar ReferenceVetoptim
        datetime Input_EffectDate
        bigint Input_CA
    }

    PROJECTS {
        uniqueidentifier ProjectId PK
        nvarchar Label
        nvarchar StatusCode
        nvarchar ReferenceVetoptim
        decimal Amount
        decimal CommissionRate
    }

    APPOINTMENTS {
        uniqueidentifier AppointmentId PK
        varchar Subject
        varchar ContactType
        datetime StartDate
        datetime EndDate
        varchar Location
    }

    TASKS {
        uniqueidentifier TaskId PK
        nvarchar Subject
        nvarchar Message
        date DateEcheance
    }

    NOTES {
        uniqueidentifier NoteId PK
        nvarchar Title
        nvarchar Message
        bit IsPrivate
    }

    ECHANCES {
        uniqueidentifier EcheanceId PK
        date EcheanceDate
        nvarchar Title
        decimal Amount
        nvarchar PaidStatusCode
    }

    BANKS {
        uniqueidentifier BankId PK
        nvarchar Libelle
        nvarchar IBAN
        nvarchar BIC
    }

    CITIES {
        uniqueidentifier CityId PK
        nvarchar PostalCode
        nvarchar Label
        numeric Longitude
        numeric Latitude
        varchar CodeInsee
    }

    DEPARTMENTS {
        uniqueidentifier DepartmentId PK
        nvarchar Code
        nvarchar Label
    }

    COLLABORATORS {
        uniqueidentifier CollaboratorId PK
        nvarchar VetoptimCode
        nvarchar CompanyName
        nvarchar FirstName
        nvarchar LastName
        nvarchar Email
        varchar Mobile
        varchar Phone
    }

    COMPANIES {
        uniqueidentifier CompanyId PK
        varchar CompanyName
        varchar Web
        varchar Phone
        varchar Email
    }

    PRODUCTS {
        uniqueidentifier ProductId PK
        nvarchar Label
        varchar EntityCode
        nvarchar Code
        nvarchar Parcours
        varchar Rubrique
    }

    %% Relations
    PERSONS ||--o{ PROJECTS : "participe à"
    PERSONS ||--o{ APPOINTMENTS : "a"
    PERSONS ||--o{ TASKS : "fait"
    PERSONS ||--o{ NOTES : "ajoute"
    PERSONS ||--o{ BANKS : "lié à"

    JURIDICALENTITIES ||--o{ PROJECTS : "possède"
    JURIDICALENTITIES ||--o{ APPOINTMENTS : "implique"
    JURIDICALENTITIES ||--o{ TASKS : "implique"
    JURIDICALENTITIES ||--o{ NOTES : "implique"
    JURIDICALENTITIES ||--o{ BANKS : "lié à"
    JURIDICALENTITIES ||--o{ CITIES : "localisé"

    CONTRACTS ||--o{ APPOINTMENTS : "lié à"
    CONTRACTS ||--o{ TASKS : "lié à"
    CONTRACTS ||--o{ NOTES : "lié à"
    CONTRACTS ||--o{ ECHANCES : "contient"
    CONTRACTS ||--o{ PROJECTS : "issu de"

    PROJECTS ||--o{ TASKS : "génère"
    PROJECTS ||--o{ NOTES : "annoté par"
    PROJECTS ||--o{ PRODUCTS : "concerne"

    CITIES ||--o{ DEPARTMENTS : "appartient à"
    CITIES ||--o{ COMPANIES : "adresse"
"""
    
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Diagramme BDD - Vetoptim SQL Assistant</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                min-height: 100vh;
                padding: 20px;
                margin: 0;
            }}
            .container {{
                max-width: 1400px;
                margin: 0 auto;
                background: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }}
            .logo {{
                width: 80px;
                height: auto;
                margin-bottom: 15px;
            }}
            .header h1 {{
                font-size: 2.2em;
                margin-bottom: 10px;
                font-weight: 700;
                color: white;
            }}
            .content {{
                padding: 40px;
            }}
            .nav-link {{
                display: inline-block;
                background: rgba(255, 255, 255, 0.9);
                color: #1e3a8a;
                padding: 10px 20px;
                border-radius: 20px;
                text-decoration: none;
                transition: all 0.3s ease;
                margin: 10px;
                font-weight: 600;
            }}
            .nav-link:hover {{
                background: #f59e0b;
                color: white;
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(245, 158, 11, 0.3);
            }}
            .mermaid-container {{
                background: white;
                border-radius: 15px;
                padding: 30px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                margin: 20px 0;
                overflow-x: auto;
                border: 1px solid #e2e8f0;
            }}
            .mermaid {{
                text-align: center;
            }}
            .info-box {{
                background: linear-gradient(135deg, #059669 0%, #10b981 100%);
                color: white;
                padding: 20px;
                border-radius: 15px;
                margin-bottom: 30px;
                text-align: center;
                box-shadow: 0 4px 15px rgba(5, 150, 105, 0.3);
            }}
            .info-box h3 {{
                margin: 0 0 10px 0;
                font-size: 1.3em;
            }}
            .info-box p {{
                margin: 0;
                opacity: 0.9;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img src="/static/image.png" alt="Vetoptim Logo" class="logo">
                <h1>🗺️ Diagramme des Relations</h1>
                <a href="/" class="nav-link">🏠 Retour à l'accueil</a>
                <a href="/schema" class="nav-link">📋 Voir le schéma</a>
            </div>
            <div class="content">
                <div class="info-box">
                    <h3>📊 Diagramme Entité-Relation</h3>
                    <p>Visualisation interactive des relations entre les tables de la base de données Vetoptim</p>
                </div>
                <div class="mermaid-container">
                    <div class="mermaid">
{mermaid_code}
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            mermaid.initialize({{
                startOnLoad: true,
                theme: 'default',
                themeVariables: {{
                    primaryColor: '#667eea',
                    primaryTextColor: '#2d3748',
                    primaryBorderColor: '#764ba2',
                    lineColor: '#4a5568',
                    secondaryColor: '#f7fafc',
                    tertiaryColor: '#e2e8f0'
                }},
                flowchart: {{
                    useMaxWidth: true,
                    htmlLabels: true
                }},
                er: {{
                    useMaxWidth: true,
                    htmlLabels: true
                }}
            }});
        </script>
    </body>
    </html>
    """

# --- Lancement ---
if __name__ == "__main__":
    app.run(debug=True, port=5002)
