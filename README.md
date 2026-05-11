# DataGrid Intelligence

A modern web-based AI-powered analytics platform for electricity distribution, smart metering, and energy data. Ask natural language questions about your data and get instant SQL queries, charts, and insights.

## Overview

This project combines:
- **Natural Language Processing**: Convert plain English questions to SQL queries
- **AI Engines**: Claude (Anthropic), Gemini (Google), with offline rule-based fallback
- **Vector Search**: Semantic pattern matching using ChromaDB + sentence-transformers
- **Fast Analytics**: DuckDB for in-memory SQL execution on Parquet files
- **Interactive UI**: Real-time WebSocket queries with Plotly charts

## Architecture

### Core Components

1. **Backend (FastAPI)**
   - `app.py`: Main server with WebSocket endpoints
   - `config.py`: Configuration and environment variables
   - `ai_engines.py`: AI API callers (Claude/Gemini)
   - `query_runner.py`: Query execution pipeline
   - `db_engine.py`: DuckDB wrapper with union views
   - `file_handlers.py`: File upload processors
   - `chart_utils.py`: Plotly chart generator

2. **AI & Learning**
   - `query_memory.py`: Learned query patterns with vector search
   - `nl_sql.py`: Rule-based NL→SQL converter
   - `vector_memory.py`: Vector embeddings for semantic search

3. **Training**
   - `train.py`: CLI tool for manual pattern training

4. **Frontend**
   - `static/index.html`: Main UI structure
   - `static/app.js`: JavaScript logic and WebSocket client
   - `static/style.css`: Styling and responsive design

### Data Flow

```
User Query → WebSocket → app.py → ai_engines.py (if API key)
                                      ↓
                         query_runner.py → db_engine.py (SQL execution)
                                      ↓
                         chart_utils.py → Plotly JSON → Frontend
```

### File Connections

- **app.py** imports all modules and orchestrates the flow
- **config.py** provides settings to all components
- **db_engine.py** manages data that **query_runner.py** and **nl_sql.py** query
- **query_memory.py** stores patterns learned from **ai_engines.py** results
- **vector_memory.py** (integrated in query_memory.py) enables semantic search
- **file_handlers.py** processes uploads that populate **db_engine.py**
- **chart_utils.py** generates visualizations for results
- **train.py** manually adds patterns to **query_memory.py**

## Key Concepts

### Vector Database (ChromaDB)

**What it is**: A specialized database for storing and searching vector embeddings (numerical representations of text).

**How it helps**:
- **Semantic Search**: Finds similar queries even with different wording
  - Example: "show active meters" matches "list working meters"
- **Document Search**: Retrieves relevant text passages from uploaded PDFs/DOCs
- **Pattern Recall**: Remembers learned query patterns for offline use

**Implementation**:
- Uses `sentence-transformers` (all-MiniLM-L6-v2 model, ~80MB)
- Stores embeddings in local ChromaDB instance
- Cosine similarity for matching (0=identical, 2=opposite)

### Fast Analytics (DuckDB + Parquet)

**What it is**: DuckDB is an in-memory analytical database optimized for OLAP queries.

**Why fast**:
- **Columnar Storage**: Parquet files store data by columns, not rows
- **Vectorized Execution**: Processes entire columns at once
- **Memory-Mapped**: Reads data directly from disk without full loading
- **SQL Optimization**: Automatic query planning and execution

**Union Views**: Automatically combines same-schema Parquet files into virtual tables for cross-file queries.

### AI Engine Priority

1. **Claude (Anthropic)**: Primary AI, best for complex queries
2. **Gemini (Google)**: Fallback, good for general tasks
3. **Rule-Based NL→SQL**: Offline fallback using pattern matching
4. **Vector Semantic Search**: Finds similar learned patterns

### Learned Query Memory

**How it works**:
- Successful AI queries are automatically saved as patterns
- Future queries check memory first (instant response)
- Manual training via `train.py` for accuracy
- Vector search enables fuzzy matching

**Training Process**:
```
User Query → AI generates SQL → SQL executes successfully → Pattern saved
Manual: python train.py add --text "query" --sql "SELECT ..."
```

## File Explanations

### app.py (Main Server)
- **Purpose**: FastAPI server entry point with WebSocket support
- **Key Functions**:
  - `/` : Serves main HTML page
  - `/ws` : WebSocket for real-time queries
  - `/upload` : File upload endpoint
  - `/status` : App state for UI refresh
- **Connections**: Imports all modules, coordinates query execution
- **SSL**: Auto-generates certificates for HTTPS

### config.py (Configuration)
- **Purpose**: Central configuration management
- **Contains**:
  - API keys (Anthropic, Gemini)
  - File paths and limits
  - UI badges and themes
  - Supported formats (Parquet only for tabular)
- **Environment Loading**: Reads .env file automatically
- **Connections**: Used by all modules for settings

### ai_engines.py (AI Integration)
- **Purpose**: Handles API calls to Claude and Gemini
- **Features**:
  - Thread pool for non-blocking calls
  - Automatic fallback (Claude → Gemini → offline)
  - Response parsing and normalization
- **Connections**: Called by app.py for AI queries
- **Async**: Uses asyncio for FastAPI compatibility

### db_engine.py (Database Layer)
- **Purpose**: DuckDB wrapper for Parquet file management
- **Features**:
  - Schema fingerprinting for union views
  - Automatic table registration
  - SQL execution and result serialization
- **Union Views**: Combines same-schema files into "_all_data"
- **Connections**: Used by query_runner.py for SQL execution

### query_memory.py (Learning System)
- **Purpose**: Stores and retrieves learned query patterns
- **Features**:
  - Vector search integration (ChromaDB)
  - Pattern matching with confidence scores
  - Auto-learning from successful queries
- **Vector Memory**: Semantic search for patterns and documents
- **Connections**: Integrated with query_runner.py for pattern recall

### nl_sql.py (Rule-Based NL→SQL)
- **Purpose**: Offline fallback for natural language to SQL
- **Features**:
  - Master JOIN SQL for meter/consumer queries
  - Pattern matching for common query types
  - Aggregation and filtering detection
- **Connections**: Used by query_runner.py when AI unavailable

### file_handlers.py (Upload Processing)
- **Purpose**: Processes uploaded files (Parquet/DOC/PDF/TXT)
- **Features**:
  - Parquet loading with pandas
  - Document text extraction (PDF/DOCX/TXT)
  - Filename sanitization and validation
- **Connections**: Results fed to db_engine.py and vector_memory.py

### chart_utils.py (Visualization)
- **Purpose**: Generates Plotly charts from DataFrame results
- **Features**:
  - Auto-chart detection based on data types
  - Manual chart type overrides
  - Consistent theming and colors
- **Connections**: Called by query_runner.py after SQL execution

### train.py (Training CLI)
- **Purpose**: Command-line tool for manual pattern training
- **Features**:
  - Interactive and direct pattern addition
  - Bulk import/export of patterns
  - AI-assisted training with API keys
- **Connections**: Modifies learned_queries.json used by query_memory.py

### static/index.html (UI Structure)
- **Purpose**: Main HTML page with 3-column layout
- **Features**:
  - Drag-drop file upload
  - Real-time WebSocket connection
  - Tabbed results (Chart/Table/SQL)
- **Connections**: Loads app.js and style.css

### static/app.js (Frontend Logic)
- **Purpose**: JavaScript for UI interactions and WebSocket client
- **Features**:
  - File upload handling
  - Query sending and result rendering
  - Chart rendering with Plotly
  - Table display and CSV export
- **Connections**: Communicates with app.py WebSocket

### static/style.css (Styling)
- **Purpose**: Responsive CSS with design system
- **Features**:
  - CSS custom properties for theming
  - Grid layout for desktop/tablet/mobile
  - Component styling (buttons, cards, toasts)
- **Connections**: Applied to index.html elements

## Setup and Usage

1. **Install Dependencies**:
   ```bash
   pip install fastapi uvicorn duckdb pandas plotly chromadb sentence-transformers
   # Optional: pypdf python-docx for document processing
   ```

2. **Configure API Keys** (create .env):
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxx
   GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

3. **Run Server**:
   ```bash
   python app.py
   # Opens https://localhost:8899
   ```

4. **Upload Data**: Drag Parquet files or documents

5. **Ask Questions**: Use natural language queries

6. **Train Patterns** (optional):
   ```bash
   python train.py add --text "show all meters" --sql "SELECT * FROM Equipment"
   ```

## Performance Optimizations

- **Parquet Format**: Columnar compression, faster queries
- **DuckDB**: In-memory execution, vectorized operations
- **Vector Search**: Semantic matching beats exact string matching
- **Union Views**: Multi-file queries without data duplication
- **WebSocket**: Real-time updates without polling
- **Lazy Loading**: AI models and vector stores load on demand

## Detailed File Breakdowns

### app.py (Main Server - 200+ lines)

**Purpose**: FastAPI application entry point, handles HTTP routes and WebSocket connections for real-time query processing.

**Key Sections**:
- **Imports (lines 1-20)**: FastAPI, WebSocket, all project modules (config, ai_engines, db_engine, etc.)
- **Global State (lines 21-30)**: Shared objects for database, vector memory, learned patterns
- **SSL Setup (lines 31-50)**: Auto-generates self-signed certificates for HTTPS
- **HTTP Routes**:
  - `/` (lines 51-55): Serves static/index.html
  - `/upload` (lines 56-80): Handles file uploads, processes via file_handlers.py, registers in db_engine.py
  - `/status` (lines 81-95): Returns app state (file list, patterns count) for UI refresh
- **WebSocket Handler (lines 96-150)**: Processes "query" actions, coordinates AI engines and query execution
- **Main Function (lines 151-170)**: Starts FastAPI server with SSL

**Connections**:
- Imports all modules for coordination
- Calls ai_engines.py for AI queries
- Uses db_engine.py for SQL execution
- Integrates query_memory.py for pattern learning
- Serves static files to frontend

### config.py (Configuration - 100+ lines)

**Purpose**: Centralized configuration management with environment variable loading and constants.

**Key Sections**:
- **Environment Loading (lines 1-30)**: Custom .env parser (no external dependencies)
- **API Keys (lines 31-40)**: Anthropic Claude and Google Gemini keys
- **Paths & Limits (lines 41-60)**: Upload directories, file size limits, vector store paths
- **UI Constants (lines 61-80)**: Badge colors, supported formats, themes
- **Model Settings (lines 81-100)**: AI model names, temperatures, timeouts

**Connections**:
- Used by all modules (ai_engines.py, query_memory.py, etc.) for settings
- No dependencies on other files

### ai_engines.py (AI Integration - 150+ lines)

**Purpose**: Manages API calls to Claude and Gemini with fallback logic and response parsing.

**Key Sections**:
- **Thread Pool (lines 1-20)**: Async executor for non-blocking AI calls
- **Claude Caller (lines 21-50)**: Anthropic API integration with system prompts
- **Gemini Caller (lines 51-80)**: Google AI API integration
- **Sync Wrapper (lines 81-110)**: call_ai_sync() tries engines in priority order
- **Prompt Building (lines 111-140)**: _build_system_prompt() injects current data context
- **Response Parsing (lines 141-150)**: Normalizes responses from different APIs

**Connections**:
- Called by app.py WebSocket handler
- Uses config.py for API keys and settings
- Results fed to query_memory.py for learning

### db_engine.py (Database Layer - 120+ lines)

**Purpose**: DuckDB wrapper for loading Parquet files and executing SQL queries with union views.

**Key Sections**:
- **DuckDB Connection (lines 1-20)**: In-memory database setup
- **Schema Fingerprinting (lines 21-40)**: Creates hash of column names/types for union detection
- **Table Registration (lines 41-70)**: register_table() loads DataFrames into DuckDB
- **Union View Builder (lines 71-90)**: _rebuild_union_view() combines same-schema tables
- **Query Execution (lines 91-110)**: execute_query() runs SQL and returns DataFrame
- **Serialization (lines 111-120)**: Converts results to JSON for frontend

**Connections**:
- Used by query_runner.py for SQL execution
- Populated by file_handlers.py upload processing
- No direct AI dependencies

### query_memory.py (Learning System - 180+ lines)

**Purpose**: Manages learned query patterns using exact matching, vector search, and fuzzy matching.

**Key Sections**:
- **ChromaDB Setup (lines 1-30)**: Vector database initialization with sentence-transformers
- **Pattern Storage (lines 31-60)**: JSON file for exact patterns, ChromaDB for vectors
- **Similarity Search (lines 61-100)**: find_similar() tries exact → vector → fuzzy matching
- **Learning (lines 101-130)**: learn() auto-saves successful AI-generated patterns
- **Vector Memory Integration (lines 131-180)**: Semantic search for documents and patterns

**Connections**:
- Integrated into query_runner.py pipeline
- Uses config.py for thresholds and paths
- Stores patterns generated by ai_engines.py

### nl_sql.py (Rule-Based NL→SQL - 100+ lines)

**Purpose**: Offline fallback converter using regex patterns and template SQL for common queries.

**Key Sections**:
- **Pattern Matching (lines 1-30)**: Regex for detecting query types (count, sum, join, etc.)
- **Master JOIN SQL (lines 31-60)**: build_union_sql() creates multi-table queries
- **Aggregation Handling (lines 61-80)**: Detects SUM, AVG, COUNT patterns
- **Conversion Logic (lines 81-100)**: convert() method processes text to SQL

**Connections**:
- Used by query_runner.py when AI unavailable
- Uses db_engine.py for schema information
- No AI dependencies (pure rule-based)

### file_handlers.py (Upload Processing - 80+ lines)

**Purpose**: Processes uploaded files, extracting data from Parquet and text from documents.

**Key Sections**:
- **File Type Detection (lines 1-20)**: Checks extensions and MIME types
- **Parquet Loading (lines 21-40)**: pandas.read_parquet() with error handling
- **Document Extraction (lines 41-60)**: PDF/DOCX text extraction using pypdf/python-docx
- **Validation (lines 61-80)**: Filename sanitization and size checks

**Connections**:
- Called by app.py upload endpoint
- Results fed to db_engine.py (tabular) and vector_memory.py (documents)

### chart_utils.py (Visualization - 120+ lines)

**Purpose**: Generates Plotly chart configurations from DataFrame results with auto-detection.

**Key Sections**:
- **Chart Type Detection (lines 1-30)**: auto_chart() analyzes columns for best visualization
- **Specific Charts (lines 31-80)**: generate_bar(), generate_line(), generate_pie(), etc.
- **Theming (lines 81-100)**: Consistent colors and layout settings
- **JSON Output (lines 101-120)**: Returns Plotly figure dicts for frontend

**Connections**:
- Called by query_runner.py after SQL execution
- Results sent to frontend via WebSocket
- No dependencies on other backend modules

### train.py (Training CLI - 90+ lines)

**Purpose**: Command-line interface for manual pattern training and bulk operations.

**Key Sections**:
- **CLI Parser (lines 1-20)**: argparse setup with subcommands
- **Pattern Addition (lines 21-40)**: add_training() saves text→SQL mappings
- **Bulk Import (lines 41-60)**: ai_batch() processes files with AI
- **Interactive Mode (lines 61-90)**: cmd_ai_batch() for manual training

**Connections**:
- Modifies learned_queries.json used by query_memory.py
- Can use ai_engines.py for AI-assisted training
- Standalone CLI tool

### static/index.html (UI Structure - 150+ lines)

**Purpose**: HTML structure for the 3-column web interface with drag-drop and chat.

**Key Sections**:
- **Head (lines 1-20)**: Meta tags, Plotly.js, custom CSS/JS
- **Layout Grid (lines 21-40)**: 3-column structure (sidebar/workspace/results)
- **File Upload (lines 41-60)**: Drag-drop zone with progress indicators
- **Chat Interface (lines 61-100)**: Message bubbles, composer input
- **Results Tabs (lines 101-130)**: Chart/Table/SQL panels
- **WebSocket Setup (lines 131-150)**: Real-time connection initialization

**Connections**:
- Loads app.js and style.css
- Communicates with app.py WebSocket
- No backend dependencies

### static/app.js (Frontend Logic - 300+ lines)

**Purpose**: JavaScript client for UI interactions, file uploads, and WebSocket communication.

**Key Sections**:
- **WebSocket Client (lines 1-30)**: connectWebSocket() establishes real-time connection
- **File Upload (lines 31-60)**: Drag-drop handling and progress updates
- **Query Processing (lines 61-100)**: Sends queries, handles responses
- **Result Rendering (lines 101-200)**: renderResult() displays charts/tables/SQL
- **UI Updates (lines 201-250)**: Dynamic file list, status refresh
- **Chart Integration (lines 251-300)**: Plotly rendering and type switching

**Connections**:
- Communicates with app.py WebSocket endpoint
- Uses Plotly.js for chart rendering
- Updates index.html DOM elements

### static/style.css (Styling - 900+ lines)

**Purpose**: Comprehensive CSS with design system, responsive layout, and component styling.

**Key Sections**:
- **CSS Variables (lines 1-50)**: Color palette, spacing, typography
- **Layout Grid (lines 51-100)**: .app, .layout, responsive breakpoints
- **Components (lines 101-400)**: Buttons, cards, forms, chat bubbles
- **Sidebar (lines 401-500)**: File list, upload zone styling
- **Chat (lines 501-600)**: Message bubbles, composer, thinking indicator
- **Results (lines 601-700)**: Tabs, charts, tables, SQL display
- **Shared (lines 701-800)**: Buttons, toasts, animations
- **Responsive (lines 801-900)**: Tablet/mobile adjustments

**Connections**:
- Applied to index.html structure
- Provides visual consistency across the app</content>
<parameter name="filePath">README.md