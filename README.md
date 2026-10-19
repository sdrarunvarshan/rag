# Structure-Aware RAG Frontend

A modern Next.js frontend for the Structure-Aware RAG application.

## Features

- **Authentication**: Login and register with JWT tokens
- **Document Management**: Upload, view, and delete PDF documents
- **Query Interface**: Ask questions about your documents with structure-aware retrieval
- **Streaming Responses**: Real-time token-by-token answer generation with live status updates
- **Advanced Search**: Filter queries by specific document or search across all documents
- **Query History**: View past queries with answers, timestamps, and source information
- **Export History**: Export query history as PDF for sharing or archiving
- **Dark Mode**: Toggle between light and dark themes for comfortable viewing
- **Health Monitoring**: Check system health and readiness
- **Multi-tenant Support**: User-specific document isolation
- **Responsive Design**: Clean, modern UI with Tailwind CSS

## Prerequisites

- Node.js 18+ and npm
- Backend API running on `http://localhost:8000`
- PostgreSQL, Garage, and other backend services running

## Setup

1. **Install dependencies**:
   ```bash
   npm install
   ```

2. **Configure API URL**:
   - Edit `.env.local` if your backend runs on a different port
   - Default: `NEXT_PUBLIC_API_URL=http://localhost:8000`

3. **Start the development server**:
   ```bash
   npm run dev
   ```

4. **Open your browser**:
   - Navigate to `http://localhost:3000`

## Usage

### 1. Register
- Click "Register" on the home page
- Enter your email and password
- After registration, you'll be redirected to login

### 2. Login
- Enter your email and password
- Click "Login"
- You'll be redirected to the dashboard

### 3. Upload Documents
- Click "My Documents" tab
- Click the upload area or drag and drop a PDF
- Wait for the upload to complete
- Your document will appear in the list

### 4. Query Documents
- Click "Query Documents" tab
- Optionally select a specific document from the dropdown (advanced search)
- Type your question in the text area
- Click "Ask"
- The answer will appear below

### 5. Stream Query (Real-time)
- Click "Stream Query (Real-time)" tab
- Optionally select a specific document from the dropdown
- Type your question in the text area
- Click "Stream Ask"
- Watch the answer generate in real-time:
  - First shows "Retrieving context..." as it searches
  - Then streams the answer token by token
  - Shows "Complete" when finished
- Better for long answers and interactive experience

### 5. Advanced Search
- Use the document filter dropdown to search a specific document
- Select "All Documents" to search across all uploaded documents
- The backend filters results to only include the selected document's content

### 6. Query History
- Click "Query History" tab
- View all past queries with answers and timestamps
- See the number of sources used for each query
- Delete individual queries if needed

### 7. Export History as PDF
- Click "Query History" tab
- Click "Export as PDF" button
- PDF file will download with all your queries and answers
- Format includes questions, answers, and timestamps

### 8. Toggle Dark Mode
- Click the sun/moon icon in the header
- Theme toggles instantly between light and dark modes
- Preference is saved for future visits

### 9. Check System Health
- Use the "Check Health" and "Check Readiness" buttons
- View the status of backend services

## Tech Stack

- **Next.js 15** with App Router
- **TypeScript** for type safety
- **Tailwind CSS** for styling
- **React 19** for UI components
- **jsPDF** for PDF generation

## API Integration

The frontend communicates with the backend API using:
- JWT authentication (Bearer token in Authorization header)
- RESTful endpoints
- JSON responses

## For Interviews

When presenting this project:

1. **Show the Architecture**:
   - Explain the separation between frontend and backend
   - Describe JWT authentication flow
   - Explain the multi-tenant isolation

2. **Demonstrate Features**:
   - Upload a PDF and show it appearing in the document list
   - Ask a question using the regular "Query Documents" tab
   - Use "Stream Query (Real-time)" to show token-by-token generation
   - Use advanced search to filter by specific document
   - Show query history with answers and timestamps
   - Export query history as PDF
   - Toggle dark mode for comfortable viewing
   - Show the health check endpoints
   - Demonstrate user isolation (register two users, show they can't see each other's documents)

3. **Explain the Backend**:
   - Mention Docling for PDF parsing
   - Explain hybrid search (pgvector + BM25)
   - Describe hierarchical expansion
   - Note the security fixes (tenant isolation, cache invalidation, etc.)

4. **Show the Code**:
   - Point out the clean component structure
   - Explain the API integration
   - Show the state management
   - Demonstrate error handling

## Troubleshooting

**CORS Errors**:
- Ensure backend CORS middleware allows your frontend origin
- Check that `NEXT_PUBLIC_API_URL` is correct

**Login Fails**:
- Verify backend is running
- Check browser console for error messages
- Ensure JWT secret is configured in backend

**Upload Fails**:
- Check file size limit in backend (default 50MB)
- Verify Garage storage is running
- Check backend logs for errors

## Future Enhancements

- Document preview in browser
- More advanced search filters (date range, content type, metadata)
- Query history search and pagination
- More export formats (CSV, JSON, Markdown)
- Custom themes and color schemes
- Query analytics and statistics
- Collaboration features (share queries with other users)
- Voice input for queries
- Multiple languages support
