"""Multi-Language Repository and Parsing Tests.
Verifies:
- JavaScript / TypeScript source parsing (components, functions, routes, API calls)
- Java class, interface, and method extraction
- SQL DDL schema extraction (tables, columns, foreign keys)
- Full indexing pipeline on a mixed-language repository (TypeScript frontend + Python backend + SQL migrations)
"""
from __future__ import annotations
import os, tempfile, shutil
from app.analysis.structural.parsers import parse_js_ts, parse_source
from app.analysis.functional.entities import _extract_sql_entities
from app.analysis.structural.pipeline import run_structural_analysis
from app.analysis.functional.pipeline import run_functional_analysis
from app.knowledge_base.pipeline import run_kb_indexing
from app.models.database import SessionLocal
from app.models.models import Project, SourceFile, CodeSymbol, DataEntity
from app.reasoning import summarize_project, answer_functional_question


def test_typescript_advanced_parsing():
    ts_code = '''
    import React, { useState } from 'react';

    export interface UserProfile {
        id: string;
        email: string;
    }

    export const UserProfileCard = ({ profile }: { profile: UserProfile }) => {
        return <div className="card">{profile.email}</div>;
    };

    export async function fetchUserData(userId: string): Promise<UserProfile> {
        const res = await fetch(`/api/users/${userId}`);
        return res.json();
    }

    router.get('/api/users/:id', getUserHandler);
    '''
    syms = parse_js_ts(ts_code)
    kinds = {s.kind for s in syms}
    names = {s.name for s in syms}

    assert "component" in kinds
    assert "UserProfileCard" in names
    assert any("fetchUserData" in n for n in names)
    assert any("GET /api/users/:id" in n for n in names)
    assert any("api_call:" in n for n in names)


def test_java_parsing():
    java_code = '''
    package com.example.service;

    public class PaymentProcessor {
        private String merchantId;

        public PaymentResult executePayment(PaymentRequest request) {
            validateRequest(request);
            return gateway.charge(request.getAmount());
        }

        private boolean validateRequest(PaymentRequest request) {
            return request != null && request.getAmount() > 0;
        }
    }
    '''
    syms = parse_source(java_code, "java")
    kinds = {s.kind for s in syms}
    names = {s.name for s in syms}

    assert "class" in kinds
    assert "PaymentProcessor" in names
    assert "function" in kinds
    assert any(n in names for n in ["executePayment", "validateRequest"])


def test_sql_ddl_schema_extraction():
    sql_schema = '''
    CREATE TABLE IF NOT EXISTS patients (
        patient_id VARCHAR(64) PRIMARY KEY,
        full_name VARCHAR(255) NOT NULL,
        birth_date DATE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE appointments (
        id SERIAL PRIMARY KEY,
        patient_id VARCHAR(64) REFERENCES patients(patient_id),
        scheduled_time TIMESTAMP NOT NULL,
        status VARCHAR(32) DEFAULT 'pending',
        notes TEXT
    );
    '''
    entities = _extract_sql_entities(sql_schema)
    assert len(entities) == 2

    patients_table = next((e for e in entities if e["name"] == "patients"), None)
    assert patients_table is not None
    assert "patient_id" in patients_table["fields"]
    assert "full_name" in patients_table["fields"]

    appointments_table = next((e for e in entities if e["name"] == "appointments"), None)
    assert appointments_table is not None
    assert "patient_id" in appointments_table["fields"]
    assert "status" in appointments_table["fields"]
    assert "patients" in appointments_table["relations"]


def test_mixed_language_repository_indexing():
    """Verify that a project with mixed languages (Python, TypeScript, SQL) is indexed and answers questions."""
    tmp = tempfile.mkdtemp(prefix="codesense_mixed_")
    db = SessionLocal()
    try:
        # 1. Create mixed repository files
        # Backend Python
        os.makedirs(os.path.join(tmp, "backend", "routes"), exist_ok=True)
        with open(os.path.join(tmp, "backend", "routes", "billing.py"), "w", encoding="utf-8") as f:
            f.write('''
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.post("/api/invoices/process")
def process_invoice(invoice_id: str, amount: float):
    """Process customer billing invoice and mark as paid."""
    if amount <= 0:
        raise ValueError("Invoice amount must be positive")
    return {"status": "paid", "invoice_id": invoice_id}
''')

        # Frontend TypeScript
        os.makedirs(os.path.join(tmp, "frontend", "src"), exist_ok=True)
        with open(os.path.join(tmp, "frontend", "src", "InvoiceView.tsx"), "w", encoding="utf-8") as f:
            f.write('''
import React from 'react';

export default function InvoiceView({ invoiceId }) {
    const handlePay = async () => {
        await fetch('/api/invoices/process');
    };
    return <button onClick={handlePay}>Pay Invoice</button>;
}
''')

        # Database SQL Migration
        os.makedirs(os.path.join(tmp, "migrations"), exist_ok=True)
        with open(os.path.join(tmp, "migrations", "001_init.sql"), "w", encoding="utf-8") as f:
            f.write('''
CREATE TABLE invoices (
    invoice_id VARCHAR(64) PRIMARY KEY,
    amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    created_at TIMESTAMP
);
''')

        # README
        with open(os.path.join(tmp, "README.md"), "w", encoding="utf-8") as f:
            f.write('''
# Billing and Invoicing Platform
Handles customer billing, invoice processing, and payment workflows.
''')

        # 2. Index project
        p = Project(name="MixedBillingApp", repo_provider="github", repo_url="https://github.com/org/billing", default_branch="main")
        db.add(p)
        db.flush()

        db.add(SourceFile(project_id=p.id, path="backend/routes/billing.py", language="python", hash="h1"))
        db.add(SourceFile(project_id=p.id, path="frontend/src/InvoiceView.tsx", language="typescript", hash="h2"))
        db.add(SourceFile(project_id=p.id, path="migrations/001_init.sql", language="sql", hash="h3"))
        db.add(SourceFile(project_id=p.id, path="README.md", language="markdown", hash="h4"))
        db.commit()

        run_structural_analysis(db, p.id, tmp)
        run_functional_analysis(db, p.id, tmp)
        run_kb_indexing(db, p.id, tmp)

        # 3. Verify multi-language file indexing
        files = db.query(SourceFile).filter(SourceFile.project_id == p.id).all()
        langs = {sf.language for sf in files}
        assert "python" in langs
        assert "typescript" in langs
        assert "sql" in langs

        # 4. Verify symbols & entities extracted from multiple languages
        syms = db.query(CodeSymbol).filter(CodeSymbol.project_id == p.id).all()
        sym_names = {s.name for s in syms}
        assert any("POST /api/invoices/process" in s for s in sym_names)
        assert any("InvoiceView" in s for s in sym_names)

        ents = db.query(DataEntity).filter(DataEntity.project_id == p.id).all()
        ent_names = {e.name.lower() for e in ents}
        assert "invoices" in ent_names

        # 5. Verify functional QA on mixed repo
        ans = answer_functional_question(db, p.id, "How does invoice processing work?")
        assert ans["status"] == "SUCCESS"
        assert "Answer" in ans["answer"] or "How It Works" in ans["answer"]
        assert ans["confidence"] in ("High", "Medium")

    finally:
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)
