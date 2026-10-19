# Structure-Aware RAG Frontend

A modern Next.js frontend for the Structure-Aware RAG application.

## Features

- **Authentication**: Login and register with JWT tokens
- **Document Management**: Upload, view, and delete PDF documents
- **Query Interface**: Ask questions about your documents with structure-aware retrieval
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
- Type your question in the text area
- Click "Ask"
- The answer will appear below

### 5. Check System Health
- Use the "Check Health" and "Check Readiness" buttons
- View the status of backend services

## Tech Stack

- **Next.js 15** with App Router
- **TypeScript** for type safety
- **Tailwind CSS** for styling
- **React 19** for UI components

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
   - Ask a question and show the retrieved answer
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

- Streaming responses for real-time answers
- Document preview in browser
- Advanced search filters
- Query history
- Export results
- Dark mode toggle
