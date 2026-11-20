import streamlit as st
import pandas as pd
import io
import time
from typing import List
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

st.set_page_config(page_title="ContoSnapAI - Contabilità & Gestionali", page_icon="📊", layout="wide")

# --- CONFIGURAZIONE COMMERCIALE ---
CODICI_PRO_VALIDI = ["VIP2026", "CLIENTEPRO", "STUDIO100"]
LIMITE_GRATIS = 2
LINK_PAGAMENTO_STRIPE = "https://stripe.com"

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    API_KEY = ""

# --- INTESTAZIONE ---
st.title("📊 ContoSnapAI — Estrattore Contabile per Aziende e Commercialisti")
st.markdown("Estrae **testata fiscale**, **singole righe articolo** ed esporta in formato **Excel Commercialista** o **Gestionale (Fatture in Cloud / Easyfatt)**.")

# --- BARRA LATERALE ---
with st.sidebar:
    st.header("💎 Piano Attivo")
    codice_inserito = st.text_input("Hai un Codice Licenza PRO?", type="password", placeholder="Inserisci codice...")
    utente_pro = codice_inserito.strip().upper() in CODICI_PRO_VALIDI
    
    if utente_pro:
        st.success("✅ **PIANO PRO ATTIVO**\nElaborazione massiva illimitata sbloccata!")
    else:
        st.info(f"🆓 **PIANO GRATUITO**\nMax **{LIMITE_GRATIS} documenti** per volta.")
        st.markdown("### Passa a PRO (19€/mese)")
        st.markdown("- ✅ Caricamento massivo illimitato\n- ✅ Estrazione singole righe prodotto\n- ✅ Export per Fatture in Cloud / Easyfatt")
        st.link_button("💳 Ottieni Codice PRO", LINK_PAGAMENTO_STRIPE, use_container_width=True)

# --- STRUTTURA DATI (TESTATA + SINGOLE RIGHE PRODOTTO) ---
class RigaArticolo(BaseModel):
    descrizione: str = Field(description="Descrizione del prodotto o servizio acquistato")
    quantita: float = Field(description="Quantità acquistata, usa 1.0 se non specificata")
    prezzo_unitario: float = Field(description="Prezzo unitario netto o lordo, usa 0.0 se non presente")
    aliquota_iva_riga: str = Field(description="Aliquota IVA della riga (es. 22%, 10%, 4%, Esente)")
    totale_riga: float = Field(description="Importo totale della singola riga")

class DatiFatturaCompleta(BaseModel):
    tipo_documento: str = Field(description="Tipo documento (es. Fattura, Scontrino, Ricevuta, DDT/Bolla, Nota di Credito)")
    fornitore: str = Field(description="Ragione sociale completa del fornitore/emittente")
    partita_iva: str = Field(description="Partita IVA del fornitore (11 cifre senza IT)")
    codice_fiscale: str = Field(description="Codice Fiscale del fornitore se diverso o uguale alla P.IVA")
    numero_documento: str = Field(description="Numero progressivo del documento")
    data_documento: str = Field(description="Data documento in formato GG/MM/AAAA")
    imponibile: float = Field(description="Totale imponibile netto (senza IVA)")
    aliquota_iva_prevalente: str = Field(description="Aliquota IVA principale (es. 22%, 10%, 4%, Mista)")
    iva: float = Field(description="Totale importo IVA")
    totale: float = Field(description="Totale documento da pagare")
    metodo_pagamento: str = Field(description="Metodo di pagamento rilevato (es. Bonifico, Carta/POS, Contanti, RiBa, N/D)")
    conto_contabile: str = Field(description="Suggerimento conto contabile (es. Merci c/acquisti, Spese carburante, Utenze, Vitto e alloggio, Consulenze)")
    articoli: List[RigaArticolo] = Field(description="Elenco di tutte le singole righe prodotto/servizio presenti nel documento")

def estrai_documento_completo(file_bytes, mime_type, chiave_api):
    client = genai.Client(api_key=chiave_api)
    
    prompt = """
    Sei un assistente esperto in contabilità italiana. Analizza visivamente questo documento (fattura, scontrino o bolla).
    Estrai sia i dati generali della testata fiscale sia OGNI SINGOLA RIGA di prodotto o servizio elencata nel corpo del documento.
    Se un dato non è presente, inserisci 'N/D' per i testi o 0.0 per i numeri.
    """
    
    documento_allegato = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
    modelli_da_provare = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"]
    ultimo_errore = None
    
    for modello in modelli_da_provare:
        for tentativo in range(2):
            try:
                response = client.models.generate_content(
                    model=modello,
                    contents=[documento_allegato, prompt],
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": DatiFatturaCompleta,
                    },
                )
                return response.parsed
            except Exception as e:
                ultimo_errore = e
                if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                    time.sleep(2)
                else:
                    raise e
    raise ultimo_errore

# --- AREA DI CARICAMENTO ---
uploaded_files = st.file_uploader(
    "Trascina qui PDF, scansioni o foto di scontrini/fatture",
    type=["pdf", "jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

if uploaded_files:
    if not API_KEY:
        st.error("⚠️ Servizio non configurato (manca GEMINI_API_KEY nei Secrets).")
    elif not utente_pro and len(uploaded_files) > LIMITE_GRATIS:
        st.warning(f"⚠️ Il Piano Gratuito permette massimo **{LIMITE_GRATIS} file** per volta. Inserisci un Codice PRO a sinistra per sbloccare l'invio massivo.")
    else:
        if st.button("🚀 Avvia Estrazione Contabile", type="primary"):
            lista_testate = []
            lista_articoli = []
            barra_progresso = st.progress(0)
            
            for indice, file in enumerate(uploaded_files):
                try:
                    dati = estrai_documento_completo(file.getvalue(), file.type, API_KEY)
                    
                    # 1. Aggiungi riga al Riepilogo Contabile
                    lista_testate.append({
                        "File": file.name,
                        "Tipo Doc.": dati.tipo_documento,
                        "Data": dati.data_documento,
                        "N. Documento": dati.numero_documento,
                        "Fornitore": dati.fornitore,
                        "Partita IVA": dati.partita_iva,
                        "Codice Fiscale": dati.codice_fiscale,
                        "Imponibile (€)": dati.imponibile,
                        "Aliquota IVA": dati.aliquota_iva_prevalente,
                        "IVA (€)": dati.iva,
                        "Totale (€)": dati.totale,
                        "Pagamento": dati.metodo_pagamento,
                        "Conto Contabile": dati.conto_contabile
                    })
                    
                    # 2. Aggiungi tutte le singole righe prodotto al Dettaglio Articoli
                    for art in dati.articoli:
                        lista_articoli.append({
                            "File Origine": file.name,
                            "Data Doc.": dati.data_documento,
                            "N. Documento": dati.numero_documento,
                            "Fornitore": dati.fornitore,
                            "Descrizione Articolo": art.descrizione,
                            "Quantità": art.quantita,
                            "Prezzo Unit. (€)": art.prezzo_unitario,
                            "IVA %": art.aliquota_iva_riga,
                            "Totale Riga (€)": art.totale_riga
                        })
                        
                except Exception as e:
                    st.error(f"Errore su {file.name}: {e}")
                
                barra_progresso.progress((indice + 1) / len(uploaded_files))
            
            if lista_testate:
                df_testate = pd.DataFrame(lista_testate)
                df_articoli = pd.DataFrame(lista_articoli) if lista_articoli else pd.DataFrame(columns=["Nessun articolo rilevato"])
                
                st.success(f"✅ Elaborati {len(lista_testate)} documenti e estratte {len(lista_articoli)} righe articolo!")
                
                # Schede interattive nel browser
                tab1, tab2 = st.tabs(["📑 Riepilogo Fiscale (Commercialista)", "🛒 Dettaglio Singole Righe Prodotto"])
                
                with tab1:
                    df_testate_mod = st.data_editor(df_testate, use_container_width=True, key="editor_testate")
                
                with tab2:
                    df_articoli_mod = st.data_editor(df_articoli, use_container_width=True, key="editor_articoli")
                
                st.divider()
                st.subheader("📥 Scarica i tracciati pronti all'uso")
                col1, col2 = st.columns(2)
                
                # EXPORT 1: Excel Multi-Foglio per Commercialista
                with col1:
                    buffer_comm = io.BytesIO()
                    with pd.ExcelWriter(buffer_comm, engine='openpyxl') as writer:
                        df_testate_mod.to_excel(writer, index=False, sheet_name='Riepilogo_Contabile')
                        df_articoli_mod.to_excel(writer, index=False, sheet_name='Dettaglio_Articoli')
                    
                    st.download_button(
                        label="📊 Scarica Excel Commercialista (2 Fogli)",
                        data=buffer_comm.getvalue(),
                        file_name="ContoSnapAI_Commercialista.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                
                # EXPORT 2: Tracciato compatibile con Gestionali (Fatture in Cloud / Easyfatt)
                with col2:
                    df_gestionale = pd.DataFrame({
                        "Data documento": df_testate_mod["Data"],
                        "Numero documento": df_testate_mod["N. Documento"],
                    df_gestionale = pd.DataFrame({
                        "Data documento": df_testate_mod["Data"],
                        "Numero documento": df_testate_mod["N. Documento"],
                        "Fornitore": df_testate_mod["Fornitore"],
                        "Partita IVA": df_testate_mod["Partita IVA"],
                        "Codice Fiscale": df_testate_mod["Codice Fiscale"],
                        "Descrizione": df_testate_mod["Conto Contabile"] + " - Rif. " + df_testate_mod["N. Documento"],
                        "Imponibile": df_testate_mod["Imponibile (€)"],
                        "Aliquota IVA": df_testate_mod["Aliquota IVA"],
                        "Importo IVA": df_testate_mod["IVA (€)"],
                        "Totale documento": df_testate_mod["Totale (€)"],
                        "Metodo pagamento": df_testate_mod["Pagamento"]
                    })
                    
                    buffer_gest = io.BytesIO()
                    with pd.ExcelWriter(buffer_gest, engine='openpyxl') as writer:
                        df_gestionale.to_excel(writer, index=False, sheet_name='Import_Gestionale')
                    
                    st.download_button(
                        label="🏢 Export Gestionale (Fatture in Cloud / Easyfatt)",
                        data=buffer_gest.getvalue(),
                        file_name="Import_Gestionale_ContoSnapAI.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )




