#!/usr/bin/env python3
"""Synthetic test data generator for the document pipeline.

Generates 10 realistic PDF documents with known ground truth for testing
the OCR pipeline and AI classification.

Each file is prefixed with __TEST_S{NN}__ for easy identification and cleanup.

Usage:
    python scripts/generate_test_data.py
    python scripts/generate_test_data.py --output-dir /custom/path
"""

import argparse
import os
import sys

import fitz  # PyMuPDF


# ── Document specifications ──────────────────────────────────────────────────
# Each entry: (filename, person, category, content_generator)
# The content_generator returns a list of (text, font_size) tuples for page lines

def doc_s01():
    """Facture Orange Internet - Eric / 20-Achats&Fournisseurs"""
    return (
        "Facture Orange",
        [
            ("FACTURE", 20),
            ("", 8),
            ("Orange S.A. - Facture Mensuelle", 14),
            ("", 8),
            ("Numero de facture: FAC-2024-03-4587", 11),
            ("Date d'emission: 15 mars 2024", 11),
            ("", 8),
            ("Abonne: M. Eric Martin", 12),
            ("Adresse: 42 Rue de la Republique, 75001 Paris", 10),
            ("", 8),
            ("", 8),
            ("Forfait Internet Fibre 1Gbps: 39,99 EUR", 11),
            ("Option Telephonie illimitee: 9,99 EUR", 11),
            ("Location Box Fibre: 3,00 EUR", 11),
            ("", 8),
            ("Total TTC: 52,98 EUR", 12),
            ("Date de prelevement: 30 mars 2024", 10),
            ("", 8),
            ("Merci de votre confiance. - Service Client Orange", 10),
        ],
    )


def doc_s02():
    """Releve Bancaire Compte Conjoint - Famille / 90-Financier"""
    return (
        "Releve Bancaire",
        [
            ("RELEVE DE COMPTE", 18),
            ("", 8),
            ("Banque Nationale - Releve mensuel", 13),
            ("", 8),
            ("Compte: 0001234567890123456 (Compte Conjoint)", 10),
            ("Period: du 01/06/2024 au 30/06/2024", 10),
            ("Titulaires: Eric Martin & Sophie Martin", 10),
            ("", 8),
            ("--- Releve des operations ---", 11),
            ("03/06 Virement salaire Eric +3 250,00 EUR", 10),
            ("05/06 Prelevement EDF -85,00 EUR", 10),
            ("10/06 Courses Carrefour -156,35 EUR", 10),
            ("15/06 Virement Sophie +1 950,00 EUR", 10),
            ("20/06 Loyer appartement -1 200,00 EUR", 10),
            ("22/06 Abonnement Orange -52,98 EUR", 10),
            ("25/06 Assurance habitation -45,00 EUR", 10),
            ("28/06 Virement PEL -200,00 EUR", 10),
            ("", 8),
            ("Solde au 30 juin 2024: 4 567,89 EUR", 12),
            ("", 8),
            ("Prochain releve: 31 juillet 2024", 10),
        ],
    )


def doc_s03():
    """Bulletin de Salaire Eric - Eric / 40-ActiviteProf"""
    return (
        "Bulletin Salaire Eric",
        [
            ("BULLETIN DE SALAIRE", 18),
            ("", 8),
            ("Societe: TechInnov Solutions SAS", 12),
            ("", 8),
            ("Employe: Eric Martin", 12),
            ("Poste: Ingenieur Logiciel Senior", 11),
            ("Periode: Avril 2024", 11),
            ("", 8),
            ("--- Detail des sommes ---", 11),
            ("Salaire de base: 3 800,00 EUR", 11),
            ("Prime d'objectifs: 400,00 EUR", 11),
            ("Indemnite transport: 50,00 EUR", 11),
            ("", 8),
            ("Salaire brut: 4 250,00 EUR", 12),
            ("", 8),
            ("Cotisations salariales:", 10),
            ("- Securite sociale (6,9%): -293,25 EUR", 10),
            ("- Assurance chomage (2,4%): -102,00 EUR", 10),
            ("- Retraite (3,15%): -133,88 EUR", 10),
            ("- Mutuelle: -45,00 EUR", 10),
            ("", 8),
            ("Total cotisations: -574,13 EUR", 11),
            ("", 8),
            ("Salaire net a payer: 3 675,87 EUR", 14),
            ("Net imposable: 3 200,00 EUR", 10),
            ("", 8),
            ("Nombre d'heures travaillees: 151,67", 10),
            (" ", 10),
        ],
    )


def doc_s04():
    """Passeport Sophie - Sophie / 10-DocumentsOfficiels"""
    return (
        "Passeport Sophie",
        [
            ("REPUBLIQUE FRANCAISE", 16),
            ("", 8),
            ("PASSEPORT", 22),
            ("", 12),
            ("Nom: MARTIN", 12),
            ("Prenom: Sophie", 12),
            ("Nationalite: Francaise", 11),
            ("Date de naissance: 15/08/1988", 11),
            ("Lieu de naissance: Lyon (69)", 11),
            ("Sexe: F", 11),
            ("Taille: 1,68 m", 11),
            ("", 8),
            ("Numero: 24FR1234567", 12),
            ("Date d'emission: 10/01/2025", 11),
            ("Date d'expiration: 09/01/2035", 11),
            ("", 8),
            ("Autorite: Prefecture du Rhone", 11),
            ("", 8),
            ("Signature du titulaire:", 11),
            ("", 8),
            ("--- Ce document est la propriete de l'Etat ---", 10),
        ],
    )


def doc_s05():
    """Certificat Scolarite Elisa - Elisa / 10-DocumentsOfficiels"""
    return (
        "Certificat Scolarite Elisa",
        [
            ("COLLEGE SAINT-EXUPERY", 16),
            ("", 8),
            ("CERTIFICAT DE SCOLARITE", 18),
            ("", 8),
            ("Annee scolaire 2024-2025", 13),
            ("", 8),
            ("Je soussigne, Principal du College Saint-Exupery,", 11),
            ("certifie que l'eleve suivante est regulierement inscrite :", 11),
            ("", 8),
            ("Nom: DUPONT-MARTIN", 12),
            ("Prenom: Elisa", 12),
            ("Date de naissance: 22/03/2012", 11),
            ("Classe: 5eme B", 12),
            ("", 8),
            ("Inscription du 01/09/2024 au 31/08/2025", 11),
            ("", 8),
            ("Fait a Lyon, le 10 septembre 2024", 11),
            ("", 8),
            ("Le Principal", 11),
            ("M. Dubois", 11),
            ("", 8),
            ("Cachet du college", 10),
        ],
    )


def doc_s06():
    """Contrat Stage Loic - Loic / 40-ActiviteProf"""
    return (
        "Contrat Stage Loic",
        [
            ("CONVENTION DE STAGE", 18),
            ("", 8),
            ("Entre:", 11),
            ("Societe: BuildTech SARL", 12),
            ("Representee par: M. Laurent Fontaine", 11),
            ("", 8),
            ("Et:", 11),
            ("Stagiaire: DUPONT Loic", 12),
            ("Ne le: 05/12/2000", 11),
            ("Etablissement: Universite Lyon 1", 11),
            ("", 8),
            ("--- Objet du stage ---", 11),
            ("Intitule: Developpeur Full Stack", 12),
            ("Duree: 6 mois (du 01/02/2025 au 31/07/2025)", 11),
            ("Gratification: 650,00 EUR / mois", 11),
            ("", 8),
            ("--- Missions ---", 11),
            ("1. Developpement d'applications web", 10),
            ("2. Maintenance des bases de donnees", 10),
            ("3. Participation aux reunions d'equipe", 10),
            ("", 8),
            ("Fait a Villeurbanne, le 20 janvier 2025", 11),
            ("", 8),
            ("Signatures:", 11),
            ("Le stagiaire                    L'entreprise", 10),
        ],
    )


def doc_s07():
    """Facture Veolia Eau - Famille / 20-Achats&Fournisseurs"""
    return (
        "Facture Veolia",
        [
            ("FACTURE D'EAU", 18),
            ("", 8),
            ("Veolia Eau - Service Client", 13),
            ("", 8),
            ("Facture: V-2024-Q3-78234", 11),
            ("Date: 10 octobre 2024", 11),
            ("", 8),
            ("Abonne: M. et Mme Martin", 12),
            ("Adresse: 42 Rue de la Republique, 75001 Paris", 10),
            ("Compteur: 789456123", 10),
            ("", 8),
            ("--- Consommation ---", 11),
            ("Periode: 01/07/2024 - 30/09/2024", 10),
            ("Volume consommé: 45 m3", 10),
            ("", 8),
            ("--- Detail des montants ---", 11),
            ("Abonnement annuel (3 mois): 22,50 EUR", 10),
            ("Consommation (45 m3 x 2,15 EUR): 96,75 EUR", 10),
            ("Assainissement: 54,00 EUR", 10),
            ("Taxes et redevances: 31,25 EUR", 10),
            ("", 8),
            ("Total TTC: 204,50 EUR", 12),
            ("Echeance: 30 octobre 2024", 10),
            ("", 8),
            ("Merci de reguler sous 15 jours.", 10),
        ],
    )


def doc_s08():
    """Ordonnance Docteur Eric - Eric / 80-Sante"""
    return (
        "Ordonnance Eric",
        [
            ("ORDONNANCE", 20),
            ("", 8),
            ("Dr. Marie Dupont - Medecin Generaliste", 12),
            ("Cabinet: 15 Rue des Lilas, 69001 Lyon", 10),
            ("Tel: 04 78 12 34 56", 10),
            ("", 8),
            ("Patient: Eric Martin", 13),
            ("Date: 15 janvier 2025", 11),
            ("", 8),
            ("--- Prescription ---", 12),
            ("", 6),
            ("1. Amoxicilline 500 mg", 12),
            ("   1 gelule 3 fois par jour pendant 7 jours", 10),
            ("", 6),
            ("2. Paracetamol 1000 mg", 12),
            ("   1 comprime si douleur, max 4 par jour", 10),
            ("", 6),
            ("3. Repos de 48 heures", 12),
            ("", 6),
            ("", 6),
            ("Arret de travail: 3 jours (du 15/01 au 17/01/2025)", 11),
            ("", 8),
            ("Signature du medecin:", 11),
            ("Dr. Marie Dupont", 11),
        ],
    )


def doc_s09():
    """Software License Invoice (English) - Eric / 70-Digital"""
    return (
        "Software Invoice EN",
        [
            ("INVOICE", 20),
            ("", 8),
            ("DataSoft Inc. - Software License", 14),
            ("", 8),
            ("Invoice: INV-2024-8912-EN", 11),
            ("Date: March 5, 2024", 11),
            ("", 8),
            ("Bill To:", 11),
            ("Eric Martin", 12),
            ("42 Rue de la Republique", 10),
            ("75001 Paris, France", 10),
            ("", 8),
            ("--- License Details ---", 11),
            ("Product: DataAnalyzer Pro v4.2", 12),
            ("License Type: Perpetual + 1 year maintenance", 10),
            ("Users: 1", 10),
            ("", 8),
            ("--- Pricing ---", 11),
            ("Software License: 299,00 EUR", 11),
            ("First year maintenance (20%): 59,80 EUR", 11),
            ("", 8),
            ("Subtotal: 358,80 EUR", 11),
            ("VAT (20%): 71,76 EUR", 11),
            ("", 8),
            ("Total Due: 430,56 EUR", 14),
            ("Payment Terms: 30 days", 10),
            ("", 8),
            ("Thank you for your purchase!", 11),
            ("DataSoft Inc. - support@datasoft.com", 10),
        ],
    )


def doc_s10():
    """Facture Engie Gaz - Famille / 20-Achats&Fournisseurs"""
    return (
        "Facture Engie Gaz",
        [
            ("FACTURE DE GAZ", 18),
            ("", 8),
            ("Engie - Fournisseur de gaz naturel", 13),
            ("", 8),
            ("Facture: G-2024-12-34567", 11),
            ("Date d'emission: 5 janvier 2025", 11),
            ("", 8),
            ("Client: M. et Mme Eric Martin", 12),
            ("Adresse: 42 Rue de la Republique, 75001 Paris", 10),
            ("Point de livraison: 75001GZ789456", 10),
            ("", 8),
            ("--- Consommation ---", 11),
            ("Periode: 01/11/2024 - 31/12/2024", 10),
            ("Volume consomme: 850 kWh", 10),
            ("", 8),
            ("--- Detail des montants ---", 11),
            ("Abonnement mensuel (2 mois): 32,58 EUR", 10),
            ("Consommation (850 kWh x 0,089 EUR): 75,65 EUR", 10),
            ("Taxe interieure consommation: 12,75 EUR", 10),
            ("TVA (5,5%): 6,65 EUR", 10),
            ("", 8),
            ("Total TTC: 127,63 EUR", 12),
            ("", 8),
            ("Paiement: Prelevement automatique le 20/01/2025", 10),
            ("", 8),
            ("Suivez votre consommation sur mon-agr.engie.fr", 10),
        ],
    )


# ── Document registry ────────────────────────────────────────────────────────

DOCUMENTS = [
    ("__TEST_S01__Facture_Orange_2024-03", "Eric", "20-Achats&Fournisseurs", doc_s01),
    ("__TEST_S02__Releve_Bancaire_Compte_Conjoint_2024-06", "Famille", "90-Financier", doc_s02),
    ("__TEST_S03__Bulletin_Salaire_Eric_Avril_2024", "Eric", "40-ActiviteProf", doc_s03),
    ("__TEST_S04__Passeport_Sophie_2025", "Sophie", "10-DocumentsOfficiels", doc_s04),
    ("__TEST_S05__Certificat_Scolarite_Elisa_2024-2025", "Elisa", "10-DocumentsOfficiels", doc_s05),
    ("__TEST_S06__Contrat_Stage_Loic_Fev_2025", "Loic", "40-ActiviteProf", doc_s06),
    ("__TEST_S07__Facture_Veolia_Eau_2024_Q3", "Famille", "20-Achats&Fournisseurs", doc_s07),
    ("__TEST_S08__Ordonnance_Docteur_Eric_2025-01", "Eric", "80-Sante", doc_s08),
    ("__TEST_S09__Invoice_Software_License_EN", "Eric", "70-Digital", doc_s09),
    ("__TEST_S10__Facture_Engie_Gaz_2024-12", "Famille", "20-Achats&Fournisseurs", doc_s10),
]


def create_pdf(output_path: str, title: str, lines: list) -> None:
    """
    Create a PDF document with realistic text content.

    Args:
        output_path: Path to save the generated PDF.
        title: Internal title for the document.
        lines: List of (text, font_size) tuples for each line.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 size

    # Top margin
    y_position = 50
    left_margin = 50
    right_margin = 545

    for text, font_size in lines:
        if y_position > 800:
            # Add a new page if we're near the bottom
            page = doc.new_page(width=595, height=842)
            y_position = 50

        if text == "":
            y_position += font_size if font_size > 0 else 12
            continue

        # Choose font based on text style
        if text.isupper() and len(text) > 3:
            fontname = "helv"
        else:
            fontname = "helv"

        page.insert_text(
            fitz.Point(left_margin, y_position),
            text,
            fontsize=font_size,
            fontname=fontname,
            color=(0, 0, 0),
        )

        y_position += font_size * 1.5

    doc.save(output_path)
    doc.close()


def generate_all(output_dir: str) -> None:
    """Generate all 10 synthetic test documents."""
    os.makedirs(output_dir, exist_ok=True)

    for filename, person, category, content_func in DOCUMENTS:
        pdf_path = os.path.join(output_dir, f"{filename}.pdf")
        title, lines = content_func()
        create_pdf(pdf_path, title, lines)
        print(f"  ✓ Created: {filename}.pdf  ->  Person: {person}, Category: {category}")

    print()
    print(f"All 10 synthetic PDFs generated in: {output_dir}")
    print()
    print("Ground Truth Summary:")
    print(f"  {'Document':<50} {'Person':<12} {'Category':<25}")
    print(f"  {'-'*50} {'-'*12} {'-'*25}")
    for filename, person, category, _ in DOCUMENTS:
        print(f"  {filename:<50} {person:<12} {category:<25}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate 10 synthetic test PDFs for the document pipeline"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="tests/test_data/SYNTHETIC",
        help="Output directory for generated PDFs (default: tests/test_data/SYNTHETIC)",
    )
    args = parser.parse_args()

    print("Generating 10 synthetic test documents...")
    print()
    generate_all(args.output_dir)
    print()
    print("Done. Copy these files to the scanner folder to test the pipeline.")
    print(f"  cp {args.output_dir}/__TEST_S*.pdf /Volumes/Public/-ScansImprimante/")


if __name__ == "__main__":
    main()