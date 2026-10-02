"""
Integration tests for the Engineering Knowledge REST API endpoints.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.knowledge import get_knowledge_service
from app.main import app as fastapi_app
from app.services.embedding import MockEmbeddingService
from app.services.engineering_knowledge import EngineeringKnowledgeService
from tests.pdf_helpers import generate_scanned_blank_pdf, generate_test_pdf


@pytest.fixture(autouse=True)
def override_knowledge_service():
    """Ensure the API uses MockEmbeddingService for deterministic, fast tests."""
    mock_service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())
    fastapi_app.dependency_overrides[get_knowledge_service] = lambda: mock_service
    yield
    fastapi_app.dependency_overrides.pop(get_knowledge_service, None)


def test_create_knowledge_scope_success(client: TestClient):
    """POST /knowledge creates a new knowledge scope with 201 Created."""
    resp = client.post(
        "/knowledge",
        json={"name": "API Design Patterns", "description": "REST and GraphQL guidelines"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "API Design Patterns"
    assert data["description"] == "REST and GraphQL guidelines"
    assert data["status"] == "pending"
    assert "id" in data
    assert data["documents"] == []


def test_create_knowledge_scope_duplicate_name_fails(client: TestClient):
    """POST /knowledge with existing name returns 409 Conflict."""
    client.post("/knowledge", json={"name": "Unique Scope"})
    resp = client.post("/knowledge", json={"name": "Unique Scope"})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_list_knowledge_scopes(client: TestClient):
    """GET /knowledge returns list of scopes."""
    client.post("/knowledge", json={"name": "Scope 1"})
    client.post("/knowledge", json={"name": "Scope 2"})

    resp = client.get("/knowledge")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2
    names = [s["name"] for s in data]
    assert "Scope 1" in names
    assert "Scope 2" in names


def test_get_knowledge_scope_by_id(client: TestClient):
    """GET /knowledge/{id} returns details of the scope or 404."""
    create_resp = client.post("/knowledge", json={"name": "Lookup Scope"})
    scope_id = create_resp.json()["id"]

    resp = client.get(f"/knowledge/{scope_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == scope_id
    assert resp.json()["name"] == "Lookup Scope"

    # Non-existent
    bad_resp = client.get(f"/knowledge/{uuid4()}")
    assert bad_resp.status_code == 404


def test_delete_knowledge_scope(client: TestClient):
    """DELETE /knowledge/{id} removes the scope with 204 No Content."""
    create_resp = client.post("/knowledge", json={"name": "Delete Scope"})
    scope_id = create_resp.json()["id"]

    del_resp = client.delete(f"/knowledge/{scope_id}")
    assert del_resp.status_code == 204

    # Now 404
    get_resp = client.get(f"/knowledge/{scope_id}")
    assert get_resp.status_code == 404


def test_upload_pdf_document_success(client: TestClient):
    """POST /knowledge/{id}/documents uploads PDF and generates chunks."""
    create_resp = client.post("/knowledge", json={"name": "Upload Scope"})
    scope_id = create_resp.json()["id"]

    pdf_bytes = generate_test_pdf([
        "Page 1: Behavioral patterns like Command, State, and Strategy.",
        "Page 2: Creational patterns like Builder, Prototype, and Singleton.",
    ])

    files = {"file": ("patterns.pdf", pdf_bytes, "application/pdf")}
    upload_resp = client.post(f"/knowledge/{scope_id}/documents", files=files)

    assert upload_resp.status_code == 201
    doc_data = upload_resp.json()
    assert doc_data["filename"] == "patterns.pdf"
    assert doc_data["status"] == "completed"
    assert doc_data["error_message"] is None
    assert doc_data["chunks_count"] == 2

    # Verify parent scope is now COMPLETED
    scope_resp = client.get(f"/knowledge/{scope_id}")
    assert scope_resp.json()["status"] == "completed"
    assert len(scope_resp.json()["documents"]) == 1


def test_upload_scanned_pdf_records_failed_status(client: TestClient):
    """POST /knowledge/{id}/documents with scanned PDF records FAILED status."""
    create_resp = client.post("/knowledge", json={"name": "Scanned Upload Scope"})
    scope_id = create_resp.json()["id"]

    scanned_pdf = generate_scanned_blank_pdf(num_pages=1)
    files = {"file": ("scanned_doc.pdf", scanned_pdf, "application/pdf")}

    upload_resp = client.post(f"/knowledge/{scope_id}/documents", files=files)
    assert upload_resp.status_code == 201
    doc_data = upload_resp.json()
    assert doc_data["filename"] == "scanned_doc.pdf"
    assert doc_data["status"] == "failed"
    assert doc_data["error_message"] is not None
    assert "scanned/image-based and may require OCR" in doc_data["error_message"]
    assert doc_data["chunks_count"] == 0


def test_upload_non_pdf_rejected(client: TestClient):
    """POST /knowledge/{id}/documents with non-pdf file returns 400 Bad Request."""
    create_resp = client.post("/knowledge", json={"name": "Non-PDF Scope"})
    scope_id = create_resp.json()["id"]

    files = {"file": ("notes.txt", b"plain text content", "text/plain")}
    resp = client.post(f"/knowledge/{scope_id}/documents", files=files)
    assert resp.status_code == 400
    assert "Only PDF documents are supported" in resp.json()["detail"]


def test_upload_duplicate_filename_fails(client: TestClient):
    """POST /knowledge/{id}/documents with existing filename returns 409 Conflict."""
    create_resp = client.post("/knowledge", json={"name": "Duplicate Scope"})
    scope_id = create_resp.json()["id"]

    pdf_bytes = generate_test_pdf(["Sample engineering content."])
    files = {"file": ("guide.pdf", pdf_bytes, "application/pdf")}

    resp1 = client.post(f"/knowledge/{scope_id}/documents", files=files)
    assert resp1.status_code == 201

    files2 = {"file": ("guide.pdf", pdf_bytes, "application/pdf")}
    resp2 = client.post(f"/knowledge/{scope_id}/documents", files=files2)
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"]


def test_list_and_delete_documents_api(client: TestClient):
    """GET and DELETE /knowledge/{id}/documents/{doc_id} operations."""
    create_resp = client.post("/knowledge", json={"name": "Doc Manage Scope"})
    scope_id = create_resp.json()["id"]

    pdf_bytes = generate_test_pdf(["Sample document for deletion testing."])
    upload_resp = client.post(
        f"/knowledge/{scope_id}/documents",
        files={"file": ("to_delete.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_resp.json()["id"]

    # List
    list_resp = client.get(f"/knowledge/{scope_id}/documents")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["id"] == doc_id

    # Delete
    del_resp = client.delete(f"/knowledge/{scope_id}/documents/{doc_id}")
    assert del_resp.status_code == 204

    # Verify empty
    list_resp2 = client.get(f"/knowledge/{scope_id}/documents")
    assert list_resp2.status_code == 200
    assert len(list_resp2.json()) == 0


def test_cross_scope_document_deletion_blocked(client: TestClient):
    """DELETE /knowledge/{wrong_id}/documents/{doc_id} returns 404."""
    scope1_resp = client.post("/knowledge", json={"name": "Scope One"})
    scope2_resp = client.post("/knowledge", json={"name": "Scope Two"})

    s1_id = scope1_resp.json()["id"]
    s2_id = scope2_resp.json()["id"]

    pdf = generate_test_pdf(["Scope One exclusive content."])
    upload_resp = client.post(
        f"/knowledge/{s1_id}/documents",
        files={"file": ("s1_doc.pdf", pdf, "application/pdf")},
    )
    doc_id = upload_resp.json()["id"]

    # Attempt to delete s1's doc through s2
    cross_del = client.delete(f"/knowledge/{s2_id}/documents/{doc_id}")
    assert cross_del.status_code == 404

    # Verify document still exists in scope 1
    s1_docs = client.get(f"/knowledge/{s1_id}/documents").json()
    assert len(s1_docs) == 1
    assert s1_docs[0]["id"] == doc_id
