"""
Step 7: write a short, human-readable Word report -- the highest-
priority culverts to fix first, how much habitat each would open up
for anadromous fish, a suggested action based on the field comments,
and a draft of the official "søknad om tillatelse til fysiske tiltak i
vassdrag" (application for physical measures in a watercourse) for the
top-priority site.

Why a suggested action, and how it's decided
----------------------------------------------
For each top culvert, we suggest what kind of fix it probably needs,
using two sources, in order of trust:

  1. The biologists' own classification ("Type tiltak" from step 6's
     "Prioritering av stikkrenner" sheet), when we have it -- this is
     a real expert judgement, not a guess.
  2. Otherwise, simple keyword matching over the free-text field
     comments (e.g. "kvist"/"søppel" -> probably just needs clearing;
     "hopp"/"for bratt" -> probably needs a gentler transition so fish
     don't have to jump; "gitter" -> a grate may be blocking passage).
     This is a blunt heuristic over Norwegian free text, meant as a
     starting point for someone who knows the site to confirm or
     correct -- not an engineering assessment. The report always
     labels which of the two a suggestion came from.

About the application form
----------------------------
The form (search for "søknadsskjema fysiske tiltak i vassdrag") isn't
a fillable PDF -- it's a plain document with blank lines for
handwritten answers, one application per physical measure at one
specific site. This script drafts one for the single highest-priority
site, filling in only what genuinely comes from this project's data
(kommune, vassdrag, coordinates, a description of the problem and the
suggested measure) and leaving every applicant-specific, legal, or
site-visit-dependent field (who's applying, landowner sign-off, formal
ecological assessment, mitigation plan, signature) blank and clearly
marked -- filling those in would mean guessing at things only a person
can actually know or decide.

**Double-check the submission address before sending anything.** The
form we were given names "Fylkesmannen i Rogaland" -- both an outdated
term (Norway renamed "Fylkesmannen" to "Statsforvalteren" nationally in
2021) and the wrong county for this project (Rogaland, not Agder). We
have not guessed a replacement address; look up the correct current
one on Statsforvalteren i Agder's own site before submitting anything.

Usage
-----
    python scripts/07_lag_rapport.py --kommune Arendal --antall 5
"""

import argparse
import re
from datetime import date
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
IN_CSV_CANDIDATES = [
    ROOT / "data" / "processed" / "kulvert_punkter_feltdata.csv",
    ROOT / "data" / "processed" / "kulvert_punkter_oppstrom.csv",
    ROOT / "data" / "processed" / "kulvert_punkter_med_hoyde.csv",
    ROOT / "data" / "processed" / "kulvert_punkter.csv",
]
OUT_DOCX = ROOT / "output" / "prioriteringsrapport.docx"

BARRIER_ORDER = ["Absolutt", "Partiell"]
SNAP_WARNING_DISTANCE_M = 50.0

# Prefer the biologists' own classification when we have it.
ACTION_FROM_TYPE_TILTAK = {
    "LettRensk": "Lett rensk: fjerne kvist, søppel og sedimenter som blokkerer kulverten.",
    "MindreUtbedring": "Mindre utbedring: justere eller fjerne en konkret hindring (f.eks. gitter, rist eller gammel innretning).",
    "OmfattendeUtbedring": "Omfattende utbedring: sannsynligvis bytte eller ombygging av kulverten.",
    "UavklartMåBefares": "Uavklart -- befaring i felt nødvendig for å fastslå riktig tiltak.",
    "Uklassifisert": "Ikke klassifisert av fagperson -- befaring anbefales.",
}

# Fallback: ordered keyword rules over the free-text comments. First
# match wins. Deliberately blunt -- a starting point to verify, not an
# engineering assessment.
KEYWORD_RULES = [
    (r"demning|ålekar|gammel\w* (rør|innretning)", "Fjerne fysisk hindring (f.eks. gammel demning/innretning) som blokkerer kulverten."),
    (r"gitter|rist", "Justere eller fjerne gitter/rist som hindrer fiskepassasje."),
    (r"kvist|søppel|slam|rusk|tettes|gjengrodd", "Rensk: fjerne kvist, søppel og sedimenter som blokkerer eller tetter kulverten."),
    (r"hopp|for bratt|stor\w* fall|høy\w* fall|\bfoss\b", "Redusere fallhøyde: lage en slak overgang/terskel slik at fisk slipper å hoppe."),
    (r"underdimensjonert|for lite rør|for lit\w+|for smal\w*", "Vurdere å bytte til et større/riktigere dimensjonert rør."),
    (r"\btørt\b|lite vann|lav vannføring", "Vurdere vannføring gjennom kulverten ved lav vannstand (lavvannsløsning)."),
    (r"blokker", "Fjerne det som blokkerer kulverten (se kommentar for detaljer)."),
]

DEFAULT_ACTION = "Ingen tydelig årsak identifisert i kommentarene -- befaring i felt anbefales for å avklare riktig tiltak."


def suggest_action(row):
    """Returns (suggested_action_text, source_label)."""
    type_tiltak = row.get("type_tiltak")
    if pd.notna(type_tiltak) and str(type_tiltak).strip():
        key = str(type_tiltak).strip()
        text = ACTION_FROM_TYPE_TILTAK.get(key, f"Fagperson har klassifisert tiltaket som: {key}.")
        return text, "fagpersonens egen vurdering"

    combined = " ".join(
        str(row.get(col, "")) for col in ("kommentar", "fagkommentar", "problem_beskrivelse") if pd.notna(row.get(col))
    ).strip()
    if not combined:
        return DEFAULT_ACTION, "ingen kommentar tilgjengelig"

    combined_lower = combined.lower()
    for pattern, action in KEYWORD_RULES:
        if re.search(pattern, combined_lower):
            return action, "nøkkelord i feltkommentar"
    return DEFAULT_ACTION, "kommentar fantes, men ingen kjente nøkkelord"


def fmt(value, unit="", decimals=2):
    if pd.isna(value) or str(value).strip() in ("", "nan"):
        return "(ikke oppgitt)"
    if isinstance(value, float):
        return f"{round(value, decimals)}{unit}"
    return f"{value}{unit}"


def add_heading(doc, text, level=1):
    doc.add_heading(text, level=level)


def add_kv_table(doc, rows):
    """A simple two-column key/value table."""
    table = doc.add_table(rows=0, cols=2)
    table.style = "Light Grid Accent 1"
    for label, value in rows:
        row = table.add_row().cells
        row[0].text = label
        row[1].text = value
    return table


def build_report(culverts, kommune, top_n):
    # Culverts flagged score_upalitelig (see step 4: FKB-Vann confirms
    # real water at the field point, but Elvenett has no edge anywhere
    # nearby, so the trace was forced onto a distant, likely unrelated
    # stream) are excluded from the ranked list -- their score number is
    # not trustworthy enough to sort a "fix this first" recommendation
    # by, even though the culvert itself is still a real, mapped barrier.
    has_unreliable_col = "score_upalitelig" in culverts.columns
    unreliable = culverts[culverts["score_upalitelig"]] if has_unreliable_col else culverts.iloc[0:0]
    rankable = culverts[~culverts["score_upalitelig"]] if has_unreliable_col else culverts

    top = rankable.sort_values("prioriteringsscore", ascending=False).head(top_n).copy()
    top["_action"], top["_action_source"] = zip(*top.apply(suggest_action, axis=1))

    doc = Document()
    doc.add_heading(f"Prioriteringsrapport -- vandringshinder for fisk, {kommune} kommune", level=0)
    p = doc.add_paragraph(f"Generert {date.today().isoformat()} fra prosjektets kartleggingsdata.")
    p.runs[0].italic = True

    add_heading(doc, "Om denne rapporten", level=1)
    doc.add_paragraph(
        "Rapporten er generert automatisk fra kulvertregistreringen (\"Aggregert data\") kombinert "
        "med NVEs elvenett og innsjødata, og fagpersonenes egne feltvurderinger der de finnes "
        "(\"Prioritering av stikkrenner\"). Prioriteringsscore er en relativ rangering (0-100) av "
        "hvor mye elve- og innsjøhabitat som blir tilgjengelig for fisk dersom det aktuelle "
        "vandringshinderet fjernes, sammenlignet med de andre kartlagte hinderne."
    )
    doc.add_paragraph(
        "Foreslått tiltak er enten fagpersonens egen klassifisering (der den finnes) eller et "
        "enkelt forslag basert på nøkkelord i feltkommentarene. Sistnevnte er ment som et "
        "utgangspunkt for videre vurdering, ikke en faglig konklusjon -- se kilde-merkingen for "
        "hvert punkt."
    )

    add_heading(doc, "Sammendrag", level=1)
    n_total = len(culverts)
    n_absolutt = (culverts["barrier_category"] == "Absolutt").sum()
    n_partiell = (culverts["barrier_category"] == "Partiell").sum()
    top_km = top["oppstrom_lengde_km"].sum()
    top_km2 = top["oppstrom_innsjo_km2"].sum() if "oppstrom_innsjo_km2" in top.columns else 0.0
    doc.add_paragraph(
        f"{n_total} kartlagte vandringshinder i {kommune} kommune ({n_absolutt} totale, "
        f"{n_partiell} delvise). De {len(top)} høyest prioriterte alene tilsvarer til sammen "
        f"ca. {round(top_km, 2)} km elvestrekning og {round(top_km2, 2)} km2 innsjøareal som kan "
        f"åpnes for anadrom fisk."
    )
    doc.add_paragraph(
        "Merk: dersom to av de listede hinderne ligger på samme vassdragsgren uten et hinder "
        "mellom dem, kan tallene deres delvis overlappe -- summen over er en indikasjon, ikke et "
        "eksakt systemtotal."
    ).runs[0].italic = True
    if len(unreliable) > 0:
        doc.add_paragraph(
            f"{len(unreliable)} vandringshinder er utelatt fra rangeringen under: FKB-Vann "
            f"bekrefter vann ved feltkoordinaten, men elvenett har ingen kartlagt gren i "
            f"nærheten, så prioriteringsscore for disse er trolig beregnet fra feil/urelatert "
            f"bekk og ikke pålitelig nok til å rangere etter. De er fortsatt reelle, kartlagte "
            f"vandringshinder -- bare ikke rangert her. Berørte steder: "
            + ", ".join(fmt(s) for s in unreliable["stedsnavn"].tolist()) + "."
        ).runs[0].italic = True

    add_heading(doc, f"Topp {len(top)} -- anbefalt prioritert rekkefølge", level=1)
    table = doc.add_table(rows=1, cols=6)
    table.style = "Light Grid Accent 1"
    header = table.rows[0].cells
    for i, text in enumerate(["#", "Sted", "Type", "Score", "Elv åpnes (km)", "Innsjø åpnes (km2)"]):
        header[i].text = text
    for rank, (_, row) in enumerate(top.iterrows(), start=1):
        cells = table.add_row().cells
        cells[0].text = str(rank)
        cells[1].text = fmt(row.get("stedsnavn"))
        cells[2].text = fmt(row.get("barrier_category"))
        cells[3].text = fmt(row.get("prioriteringsscore"), decimals=0)
        cells[4].text = fmt(row.get("oppstrom_lengde_km"))
        cells[5].text = fmt(row.get("oppstrom_innsjo_km2"))

    for rank, (_, row) in enumerate(top.iterrows(), start=1):
        doc.add_page_break()
        add_heading(doc, f"#{rank}: {fmt(row.get('stedsnavn'))}", level=1)
        add_kv_table(
            doc,
            [
                ("Kommune", fmt(row.get("kommune"))),
                ("Vassdrag", fmt(row.get("vassdrag"))),
                ("Regine", fmt(row.get("regine"))),
                ("Vurdering (vandringshinder)", fmt(row.get("barrier_label"))),
                ("Prioriteringsscore (0-100)", fmt(row.get("prioriteringsscore"), decimals=0)),
                ("Elvestrekning som åpnes", fmt(row.get("oppstrom_lengde_km"), " km")),
                ("Innsjøareal som åpnes", fmt(row.get("oppstrom_innsjo_km2"), " km2")),
                ("Koordinater (lengdegrad, breddegrad)", f"{fmt(row.get('lon_snappet', row.get('lon_ned')), decimals=6)}, {fmt(row.get('lat_snappet', row.get('lat_ned')), decimals=6)}"),
                ("Anadrom strekning (feltvurdering)", fmt(row.get("anadrom_strekning"))),
            ],
        )
        if pd.notna(row.get("snap_avstand_m")) and row.get("snap_avstand_m", 0) > SNAP_WARNING_DISTANCE_M:
            warn = doc.add_paragraph(
                f"⚠ Feltkoordinaten ligger {fmt(row.get('snap_avstand_m'), ' m', 0)} fra nærmeste "
                f"kartlagte elv/bekk -- sjekk denne posisjonen før den brukes videre (se advarsel-"
                f"laget på kartet)."
            )
            warn.runs[0].bold = True

        add_heading(doc, "Feltkommentarer", level=2)
        any_comment = False
        for label, col in [("Kommentar", "kommentar"), ("Fagkommentar", "fagkommentar"), ("Problembeskrivelse", "problem_beskrivelse")]:
            val = row.get(col)
            if pd.notna(val) and str(val).strip():
                doc.add_paragraph(f"{label}: {val}")
                any_comment = True
        if not any_comment:
            doc.add_paragraph("(Ingen feltkommentar registrert.)")

        add_heading(doc, "Foreslått tiltak", level=2)
        doc.add_paragraph(row["_action"])
        source_p = doc.add_paragraph(f"Kilde: {row['_action_source']}.")
        source_p.runs[0].italic = True

    # Application form draft for the #1 site only -- see module
    # docstring for why not all of them.
    if len(top) > 0:
        doc.add_page_break()
        add_soknad_form(doc, top.iloc[0])

    return doc


def add_soknad_form(doc, row):
    add_heading(doc, "Vedlegg: utkast til søknad om tillatelse til fysiske tiltak i vassdrag", level=1)
    doc.add_paragraph(
        "Utkast for høyest prioriterte hinder (se over). Feltene under er fylt inn med det "
        "prosjektet faktisk vet fra kartleggingen; alt annet -- søkerens opplysninger, "
        "grunneierforhold, formell faglig vurdering, avbøtende tiltak, dato og underskrift -- må "
        "fylles inn av søker selv, siden dette prosjektet ikke har grunnlag for å vite eller "
        "avgjøre det."
    )
    warn = doc.add_paragraph(
        "⚠ Skjemaet vi fikk oppgir \"Fylkesmannen i Rogaland\" som mottaker. Dette er både en "
        "utdatert betegnelse (Fylkesmannen ble til Statsforvalteren i 2021) og feil fylke for "
        "dette prosjektet (Rogaland, ikke Agder). Vi har ikke gjettet på riktig adresse -- "
        "sjekk gjeldende innsendingsadresse hos Statsforvalteren i Agder før noe sendes inn."
    )
    warn.runs[0].bold = True
    warn.runs[0].font.color.rgb = RGBColor(0xC0, 0x00, 0x00)

    def field_line(label, value=None):
        p = doc.add_paragraph()
        run = p.add_run(f"{label}: ")
        run.bold = True
        p.add_run(value if value else "[FYLLES INN AV SØKER]")

    add_heading(doc, "Søker", level=2)
    field_line("Navn")
    field_line("Adresse")
    field_line("Telefon/mobil dagtid")
    field_line("Postnummer/-sted")
    field_line("E-post")
    field_line("Navn og adresse til tiltakets eier (dersom søker representerer andre)")

    add_heading(doc, "Beskrivelse av tiltaket", level=2)
    field_line("Gårds- og bruksnummer omfattet av tiltaket")
    field_line("Kommune", fmt(row.get("kommune")))
    field_line("Vassdrag", fmt(row.get("vassdrag")))
    doc.add_paragraph("(Legg ved kart hvor tiltaksområdet er avmerket -- se dette prosjektets kart, output/agder_kulvert_kart.html.)")
    field_line("Formål med tiltaket", "Habitattiltak / biotopforbedrende tiltak")
    field_line("Bygger tiltaket på et faggrunnlag? (Ja/Nei; hvis ja, legg ved søknad)")
    field_line("Skal tiltaket gjennomføres av person(er) med elveøkologisk kompetanse? (Ja/Nei)")
    field_line("Tidspunkt for gjennomføring / varighet")

    add_heading(doc, "Beskriv tiltaket og dets omfang", level=2)
    problem_parts = [str(row.get(c)) for c in ("kommentar", "fagkommentar", "problem_beskrivelse") if pd.notna(row.get(c))]
    problem_text = " ".join(problem_parts) if problem_parts else "(ingen feltkommentar registrert)"
    doc.add_paragraph(
        f"Sted: {fmt(row.get('stedsnavn'))}. Vurdert som {fmt(row.get('barrier_label')).lower()}. "
        f"Registrert problembeskrivelse: {problem_text}"
    )
    doc.add_paragraph(f"Foreslått tiltak: {row['_action']} (kilde: {row['_action_source']}).")
    doc.add_paragraph(
        f"Dersom tiltaket gjennomføres, anslås det å åpne ca. {fmt(row.get('oppstrom_lengde_km'), ' km')} "
        f"elvestrekning og {fmt(row.get('oppstrom_innsjo_km2'), ' km2')} innsjøareal oppstrøms for "
        f"anadrom fisk (se dette prosjektets kart og rapport for grunnlag)."
    )

    field_line("Påvirker tiltaket kantvegetasjon langs vassdraget? (Ja/Nei; hvis ja, beskriv omfang)")
    field_line("Maskinbruk? (Ja/Nei; hvis ja, beskriv omfang)")

    add_heading(doc, "Forholdet til annet lovverk", level=2)
    field_line("Foreligger det tillatelse, konsesjon eller uttale fra andre sektormyndigheter?")
    field_line("Er det planlagt å søke om tillatelse eller konsesjon fra andre sektormyndigheter?")
    field_line("Er tiltaket planavklart med kommunen?")

    add_heading(doc, "Forholdet til grunneiere", level=2)
    field_line("Er tiltaket avklart med alle berørte grunneiere?")
    field_line("Grunneiere, adresser og telefonnummer")

    add_heading(doc, "Mulige konsekvenser av tiltaket", level=2)
    field_line("Er det gjennomført en faglig vurdering av mulige konsekvenser? (hvis ja, legg ved rapport/notat)")
    field_line("Søkers egen vurdering, dersom ingen faglig vurdering er gjennomført")
    field_line("Vurderer søker at tiltaket kan ha negative eller positive konsekvenser for fisk/biologisk mangfold?")
    field_line("Vurderer søker at tiltaket kan endre vannføringen eller påvirke flom-/erosjonsforholdene?")

    add_heading(doc, "Avbøtende tiltak", level=2)
    field_line("Beskriv hvordan tiltaket skal gjennomføres for å unngå negativ påvirkning på naturmiljøet")

    add_heading(doc, "Dato og underskrift", level=2)
    field_line("Dato")
    field_line("Underskrift")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kommune", default="Arendal")
    parser.add_argument("--antall", type=int, default=5, help="How many top-priority culverts to include")
    args = parser.parse_args()

    culvert_csv = next((p for p in IN_CSV_CANDIDATES if p.exists()), None)
    if culvert_csv is None:
        print("Run scripts/01_rens_kulvertdata.py first.")
        raise SystemExit(1)
    print(f"Reading {culvert_csv} ...")
    df = pd.read_csv(culvert_csv)

    if "prioriteringsscore" not in df.columns:
        print("No priority score found -- run scripts/04_koble_til_elvenett.py first")
        print("(the report needs it to rank culverts).")
        raise SystemExit(1)

    culverts = df[(df["kommune"] == args.kommune) & (df["barrier_category"].isin(BARRIER_ORDER))].copy()
    if culverts.empty:
        raise SystemExit(f"No Absolutt/Partiell culverts found for kommune='{args.kommune}'.")
    print(f"{len(culverts)} barrier culverts in {args.kommune}; reporting on the top {args.antall}")

    doc = build_report(culverts, args.kommune, args.antall)

    OUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT_DOCX)
    print(f"Saved {OUT_DOCX}")


if __name__ == "__main__":
    main()
