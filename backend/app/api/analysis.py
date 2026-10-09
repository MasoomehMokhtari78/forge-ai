"""
API router for Knowledge-Guided Analysis.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.analysis import KnowledgeAnalysisRequest, AnalysisResponse
from app.services.knowledge_guided_analysis import (
    AnalysisKnowledgeNotFoundError,
    AnalysisKnowledgeNotReadyError,
    AnalysisRepositoryNotFoundError,
    AnalysisRepositoryNotReadyError,
    FileNotFoundInRepositoryError,
    InvalidCodeScopeError,
    KnowledgeGuidedAnalysisService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


def get_analysis_service() -> KnowledgeGuidedAnalysisService:
    """Dependency injection factory for KnowledgeGuidedAnalysisService."""
    return KnowledgeGuidedAnalysisService()


@router.post(
    "/knowledge",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Perform knowledge-guided repository code analysis",
    description=(
        "Retrieves scoped evidence from both the specified repository (or file) "
        "and engineering knowledge scope, generating a grounded architectural analysis with verified citations."
    ),
)
async def analyze_with_knowledge(
    payload: KnowledgeAnalysisRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[KnowledgeGuidedAnalysisService, Depends(get_analysis_service)],
) -> AnalysisResponse:
    try:
        return await service.analyze(
            repository_id=payload.repository_id,
            knowledge_id=payload.knowledge_id,
            code_scope=payload.code_scope,
            question=payload.question,
            db=db,
        )
    except AnalysisRepositoryNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except AnalysisKnowledgeNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except FileNotFoundInRepositoryError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except AnalysisRepositoryNotReadyError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except AnalysisKnowledgeNotReadyError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except InvalidCodeScopeError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err
