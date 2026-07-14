# Indexcards OCR (Museum-Ready)

## Vision
Transform legacy museum/archive index cards into structured digital records through a user-friendly, no-code web interface powered by VLM (Vision Language Models).

## Context
GLAM institutions (Museums, Archives, Libraries, Memorial Sites) often have thousands of analog index cards. This tool provides a bridge to modern collection management systems.

## Core Features
- **No-Code Interface:** Intuitive web GUI for non-technical museum staff.
- **Dynamic Configuration:** Users define the metadata fields they want to extract.
- **VLM-Powered OCR:** Uses Qwen3-VL via OpenRouter for high-accuracy extraction from handwriting and complex layouts.
- **Batch Processing:** Handles multiple images with progress tracking.
- **Data Export:** Clean CSV output ready for database import.

## Tech Stack
- **Backend:** Python, FastAPI
- **Frontend:** React (TypeScript), TailwindCSS
- **OCR Engine:** Qwen3-VL (via OpenRouter API)
- **Data Handling:** Pandas, Pillow

## Status
- Core OCR script (`indexcard_ocr.py`) is functional.
- Prototype GUI template exists (`museum-ready-gui-template.html`).
- Integration and full web app implementation pending.
