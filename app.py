import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import anthropic
import json
import re


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GP Workforce Analyst",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.stTextInput > div > div > input {
    border: 1.5px solid #005EB8;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 15px;
}
.stButton > button {
    background-color: #005EB8;
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 500;
    font-size: 15px;
}
.stButton > button:hover { background-color: #003f7f; }

.result-box {
    background: white;
    border-left: 4px solid #005EB8;
    border-radius: 8px;
    padding: 20px 24px;
    margin: 16px 0;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.header-bar {
    background: linear-gradient(135deg, #005EB8 0%, #003f7f 100%);
    color: white;
    padding: 28px 32px;
    border-radius: 12px;
    margin-bottom: 28px;
}
</style>
""", unsafe_allow_html=True)

# ── Organisation reference ────────────────────────────────────────────────────
ORG_REFERENCE = {
    "QOX": {
        "name": "NHS Bath and North East Somerset, Swindon and Wiltshire ICB",
        "short": "BSW",
        "icb_code": "QOX",
        "aliases": ["bsw", "banes", "bath", "swindon", "wiltshire",
                    "bath and north east somerset", "bsw icb"]
    },
    "QUY": {
        "name": "NHS Bristol, North Somerset and South Gloucestershire ICB",
        "short": "BNSSG",
        "icb_code": "QUY",
        "aliases": ["bnssg", "bristol", "north somerset",
                    "south gloucestershire", "bnssg icb"]
    },
    "QT6": {
        "name": "NHS Cornwall and the Isles of Scilly ICB",
        "short": "Cornwall",
        "icb_code": "QT6",
        "aliases": ["cornwall", "cornwall icb", "isles of scilly", "cios"]
    },
    "QJK": {
        "name": "NHS Devon ICB",
        "short": "Devon",
        "icb_code": "QJK",
        "aliases": ["devon", "devon icb", "nhs devon"]
    },
    "QVV": {
        "name": "NHS Dorset ICB",
        "short": "Dorset",
        "icb_code": "QVV",
        "aliases": ["dorset", "dorset icb", "nhs dorset"]
    },
    "QR1": {
        "name": "NHS Gloucestershire ICB",
        "short": "Gloucestershire",
        "icb_code": "QR1",
        "aliases": ["gloucestershire", "glos", "gloucestershire icb", "glos icb"]
    },
    "QSL": {
        "name": "NHS Somerset ICB",
        "short": "Somerset",
        "icb_code": "QSL",
        "aliases": ["somerset", "somerset icb", "nhs somerset"]
    },
}

SW_ICB_CODES = list(ORG_REFERENCE.keys())

# ── Data loaders ──────────────────────────────────────────────────────────────
# ── Data URLs — update these each month with the new release URLs ─────────────
WORKFORCE_URL = "https://files.digital.nhs.uk/A7/B0FFAB/GPWIndividualCSV.012026.zip"
POPULATION_URL = "https://files.digital.nhs.uk/8B/19FFEE/gp-reg-pat-prac-sing-age-regions.zip"
PRACTICE_URL = "https://files.digital.nhs.uk/EC/203865/GPWPracticeCSV.012026.zip"



@st.cache_data
def load_workforce():
    import zipfile, io, requests
    with st.spinner("Loading workforce data from NHS England..."):
        r = requests.get(WORKFORCE_URL, timeout=120)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        # Find the CSV inside the zip
        csv_name = [n for n in z.namelist() if n.endswith('.csv')][0]
        df = pd.read_csv(z.open(csv_name), encoding='latin-1', low_memory=False)
    df['ICB_CODE'] = df['ICB_CODE'].astype(str).str.strip()
    df['STAFF_GROUP'] = df['STAFF_GROUP'].astype(str).str.strip()
    df['STAFF_ROLE'] = df['STAFF_ROLE'].astype(str).str.strip()
    df['AGE_YEARS'] = pd.to_numeric(df['AGE_YEARS'], errors='coerce')
    df['FTE'] = pd.to_numeric(df['FTE'], errors='coerce')
    return df


@st.cache_data
def load_population():
    import zipfile, io, requests
    with st.spinner("Loading population data from NHS England..."):
        r = requests.get(POPULATION_URL, timeout=120)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        csv_name = [n for n in z.namelist() if n.endswith('.csv')][0]
        df = pd.read_csv(z.open(csv_name), low_memory=False)
    # Keep ICB level only
    df = df[df['ORG_TYPE'] == 'ICB'].copy()
    df['ORG_CODE'] = df['ORG_CODE'].astype(str).str.strip()
    df['NUMBER_OF_PATIENTS'] = pd.to_numeric(df['NUMBER_OF_PATIENTS'], errors='coerce')
    return df

@st.cache_data
def load_practice():
    import zipfile, io, requests
    with st.spinner("Loading practice data from NHS England..."):
        r = requests.get(PRACTICE_URL, timeout=120)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        csv_files = [n for n in z.namelist() if n.endswith('.csv')]
        csv_name = max(csv_files, key=lambda n: z.getinfo(n).file_size)
        df = pd.read_csv(z.open(csv_name), encoding='latin-1', low_memory=False)
    # Show columns in the app so we can see what's there
    st.write("Files in zip:", z.namelist())
    st.write("Columns:", df.columns.tolist()[:20])
    st.stop()
    return df


@st.cache_data
def build_summary_population(_pop_df):
    """Total population per SW ICB (ALL sex, ALL age)."""
    return (
        _pop_df[
            (_pop_df['ORG_CODE'].isin(SW_ICB_CODES)) &
            (_pop_df['SEX'] == 'ALL') &
            (_pop_df['AGE'] == 'ALL')
        ][['ORG_CODE', 'NUMBER_OF_PATIENTS']]
        .rename(columns={'ORG_CODE': 'ICB_CODE', 'NUMBER_OF_PATIENTS': 'POPULATION'})
        .reset_index(drop=True)
    )


# ── System prompt ─────────────────────────────────────────────────────────────
def build_system_prompt(workforce_df, pop_df, practice_df):
    org_summary = "\n".join(
        f"  {code}: {org['name']} (aliases: {', '.join(org['aliases'][:4])})"
        for code, org in ORG_REFERENCE.items()
    )

    # Sample population data shape description
    pop_summary = build_summary_population(pop_df).to_string(index=False)

    return f"""You are an NHS data analyst assistant for NHS South West.
Answer questions about GP workforce and registered patient population data
by writing Python pandas code.

## Dataset 1: workforce_df — NHS GP Workforce, January 2026
Shape: {workforce_df.shape[0]:,} rows. Each row = one staff member.
Columns: YEAR, Month, COMM_REGION_CODE, COMM_REGION_NAME, ICB_CODE, ICB_NAME,
SUB_ICB_CODE, SUB_ICB_NAME, DATA_SOURCE, UNIQUE_IDENTIFIER, STAFF_GROUP,
DETAILED_STAFF_ROLE, STAFF_ROLE, COUNTRY_QUALIFICATION_AREA,
COUNTRY_QUALIFICATION_GROUP, AGE_BAND, AGE_YEARS, GENDER, FTE.
STAFF_GROUP values: GP, Nurses, Direct Patient Care, Admin/Non-Clinical.

## Dataset 2: pop_df — GP Registered Patients by ICB, Age and Sex
Shape: {pop_df.shape[0]:,} rows.
Columns: PUBLICATION, EXTRACT_DATE, ORG_TYPE, ORG_CODE, ONS_CODE, SEX, AGE, NUMBER_OF_PATIENTS.
ORG_TYPE is always 'ICB' in this dataset.
SEX values: ALL, MALE, FEMALE.
AGE values: single years 0-95+, plus 'ALL' for total.
To get total population per ICB: filter SEX=='ALL' and AGE=='ALL'.

## Dataset 3: practice_df — GP Workforce and Patients by Practice, January 2026
Shape: 6,172 rows. Each row = one GP practice.
Key geography columns: PRAC_CODE, PRAC_NAME, PCN_CODE, PCN_NAME, ICB_CODE, ICB_NAME
Patient columns: TOTAL_PATIENTS, TOTAL_MALE, TOTAL_FEMALE
Patient age bands: MALE_PATIENTS_0TO4, MALE_PATIENTS_65TO74, FEMALE_PATIENTS_85PLUS etc.
Workforce headcount columns use pattern: TOTAL_[GROUP]_HC e.g. TOTAL_GP_HC, TOTAL_NURSES_HC
Workforce FTE columns use pattern: TOTAL_[GROUP]_FTE e.g. TOTAL_GP_FTE, TOTAL_NURSES_FTE
Role breakdown examples: TOTAL_GP_SAL_BY_PRAC_HC (salaried GPs), TOTAL_GP_PTNR_PROV_HC (partners)
Age band columns: TOTAL_GP_HC_UNDER30, TOTAL_GP_HC_30TO34 ... TOTAL_GP_HC_70PLUS
Use this dataset for practice-level, PCN-level, or ICB-level questions 
that don't require exact individual ages or median calculations.
Use workforce_df only when exact individual ages or median calculations are needed.
Use pop_df only when you need single-year-of-age population breakdowns.

## South West ICB total populations:
{pop_summary}

## South West ICB codes and aliases:
{org_summary}

## Instructions:
Write Python pandas code to answer the question.
Store the final answer in a variable called `result`.
If a chart would help, write plotly code storing the figure in `fig`. Otherwise set fig = None.
Return ONLY a JSON object with these keys:
  "code": pandas code string (dataframes available as `workforce_df` and `pop_df`)
  "chart_code": plotly code string or null
  "explanation": 1-2 sentence plain English explanation of the result

## Rules:
- Headcount = count rows (len() or .shape[0]) NOT unique UNIQUE_IDENTIFIER values
- FTE = sum FTE column in workforce_df
- result must be a single value (int, float, DataFrame, or Series) — NEVER a dict or tuple
- For simple count questions, result = a single integer
- For comparison questions, result = a DataFrame with named columns
- Nurses = STAFF_GROUP == 'Nurses'
- GPs = STAFF_GROUP == 'GP'
- South West = ICB_CODE.isin({SW_ICB_CODES})
- For staff per 1,000 population: join workforce headcount to pop_df on ICB_CODE == ORG_CODE
- For charts use plotly.express as px, store figure in variable `fig`
- ICB_CODE in workforce_df matches ORG_CODE in pop_df directly
- When filtering pop_df by specific age, use SEX.isin(['MALE','FEMALE']) not SEX=='ALL' — the ALL row only exists for total population
- Always convert AGE to numeric before comparing: pd.to_numeric(pop_df['AGE'], errors='coerce')
- Return ONLY valid JSON, no markdown, no backticks
"""


# ── Query runner ──────────────────────────────────────────────────────────────
def run_query(question, workforce_df, pop_df, practice_df, client):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=build_system_prompt(workforce_df, pop_df, practice_df),
        messages=[{"role": "user", "content": question}]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    parsed = json.loads(raw)
    code = parsed.get("code", "")
    chart_code = parsed.get("chart_code")

    exec_globals = {
        "workforce_df": workforce_df,
        "pop_df": pop_df,
        "practice_df": practice_df,
        "pd": pd, "px": px, "go": go
    }

    exec(code, exec_globals)
    result = exec_globals.get("result")

    # Generate explanation AFTER we have the actual result
    try:
        if isinstance(result, float):
            # Round floats sensibly — if it looks like a proportion, show as percentage
            if 0 < result < 1:
                result_str = f"{result * 100:.1f}%"
            else:
                result_str = f"{result:,.1f}"
        elif isinstance(result, int):
            result_str = f"{result:,}"
        elif hasattr(result, "to_string"):
            result_str = result.to_string(index=False)[:500]
        else:
            result_str = str(result)
    except Exception:
        result_str = str(result)

    prompt = (
        "Question: " + question + "\n" +
        "Result: " + result_str + "\n" +
        "Write a single plain-English sentence explaining this result. "
        "Include the actual number from the result. No markdown."
    )
    explanation_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    explanation = explanation_response.content[0].text.strip()

    fig = None
    if chart_code:
        exec(chart_code, exec_globals)
        fig = exec_globals.get("fig")
        if fig:
            fig.update_layout(
                template="plotly_white",
                font_family="DM Sans",
                title_font_size=16,
                colorway=["#005EB8", "#0072CE", "#41B6E6",
                          "#00A499", "#78BE20", "#AE2573", "#003087"]
            )
    return result, fig, explanation


# ── Main app ──────────────────────────────────────────────────────────────────
def main():

    # Header
    st.markdown("""
    <div class="header-bar">
        <h1 style="margin:0; font-size:26px; font-weight:600;">
            🏥 GP Workforce Analyst
        </h1>
        <p style="margin:6px 0 0 0; opacity:0.85; font-size:14px;">
            NHS South West · Workforce Jan 2026 · Population Mar 2026
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Load data
    workforce_df = load_workforce()
    pop_df = load_population()
    practice_df = load_practice()
    pop_summary = build_summary_population(pop_df)
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

    # Filter to SW
    sw_wf = workforce_df[workforce_df['ICB_CODE'].isin(SW_ICB_CODES)]

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 📊 South West Snapshot")
        st.metric("Registered Patients",
                  f"{pop_summary['POPULATION'].sum():,.0f}")
        st.metric("Total Staff (headcount)",
                  f"{sw_wf['UNIQUE_IDENTIFIER'].nunique():,}")
        st.metric("Total FTE",
                  f"{sw_wf['FTE'].sum():,.0f}")
        st.metric("GPs",
                  f"{sw_wf[sw_wf['STAFF_GROUP']=='GP']['UNIQUE_IDENTIFIER'].nunique():,}")
        st.metric("Nurses",
                  f"{sw_wf[sw_wf['STAFF_GROUP']=='Nurses']['UNIQUE_IDENTIFIER'].nunique():,}")

        st.markdown("---")
        st.markdown("### 🏥 ICBs")
        for org in ORG_REFERENCE.values():
            pop_row = pop_summary[pop_summary['ICB_CODE'] == org['icb_code']]
            pop = f"{pop_row['POPULATION'].values[0]:,.0f}" if len(pop_row) else "—"
            st.markdown(f"**{org['short']}**  \n{pop} registered patients")

        st.markdown("---")
        st.caption("Workforce: NHS England, Jan 2026  \n"
                   "Population: GP registered patients, Mar 2026")

    # ── Main panel ────────────────────────────────────────────────────────────
    st.markdown("### Ask a question")

    # Example questions
    examples = [
        "How many nurses are there in Devon?",
        "What is the median age of GPs in the South West?",
        "Compare GPs per 1,000 patients by ICB as a bar chart",
        "What is the gender breakdown of GPs in BNSSG?",
        "Which ICB has the most salaried GPs?",
        "Show total FTE by staff group in Somerset",
        "How many staff per 1,000 registered patients in each SW ICB?",
        "What proportion of nurses are part time across the South West?",
    ]

    st.markdown("**Try one of these:**")
    cols = st.columns(4)
    for i, example in enumerate(examples):
        if cols[i % 4].button(example, key=f"ex_{i}", use_container_width=True):
            st.session_state["question"] = example

    st.markdown("")

    question = st.text_input(
        "Or type your own:",
        value=st.session_state.get("question", ""),
        placeholder="e.g. How many part-time GPs are there in Somerset?",
        label_visibility="collapsed"
    )

    if st.button("Ask →", type="primary") and question:
        # Clear example selection
        st.session_state["question"] = ""

        with st.spinner("Analysing..."):
            try:
                result, fig, explanation = run_query(question, workforce_df, pop_df, practice_df, client)

                st.markdown(f"""
                <div class="result-box">
                    <strong>💡 {explanation}</strong>
                </div>
                """, unsafe_allow_html=True)

                if fig:
                    st.plotly_chart(fig, use_container_width=True)

                if isinstance(result, pd.DataFrame):
                    st.dataframe(result, use_container_width=True)
                elif isinstance(result, pd.Series):
                    st.dataframe(result.to_frame(), use_container_width=True)
                elif isinstance(result, dict):
                    st.dataframe(pd.DataFrame([result]), use_container_width=True)
                # Single values (int, float, str) are already in the explanation — no second box needed

            except json.JSONDecodeError:
                st.error("The AI returned an unexpected response. "
                         "Please try rephrasing your question.")
            except Exception as e:
                st.error(f"Something went wrong: {e}")

    # Query history
    if "history" not in st.session_state:
        st.session_state["history"] = []


if __name__ == "__main__":
    main()
