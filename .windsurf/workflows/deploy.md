# /deploy - Deploy Next.js Trading Dashboard

## Goal
Deploy the modern Next.js + FastAPI trading dashboard to Vercel with all enhanced features from the original Streamlit dashboard.

## Steps
1. **Validation**: Check if `vercel` CLI is installed and authenticated.
2. **Project Structure**: Verify single-stack structure with `/api` (FastAPI) and `/frontend` (Next.js)
3. **Environment Setup**: 
   - Verify `ANTHROPIC_API_KEY` is set in Vercel environment variables
   - Pull the latest environment variables: `vercel env pull .env.local`
   - Ensure all required secrets are present for both API and frontend
4. **Dependencies**: 
   - Install frontend dependencies: `cd frontend && npm install`
   - Verify backend dependencies are in root `requirements.txt`
5. **Deployment**:
   - Run `vercel --prod` to trigger a production build
   - Vercel will automatically build both frontend (Next.js) and backend (FastAPI)
   - Capture the deployment URL and output it to the user
6. **Post-Deploy Verification**:
   - Test the frontend loads correctly at root URL
   - Test API endpoints: `/api/health`, `/api/analyze`
   - Verify streaming endpoint works: `/api/analyze-stream`
   - Check that all 4 agents (SIGNAL_AGENT, RISK_AGENT, CONSENSUS_AGENT, SIZING_AGENT) are functional
   - Test trade history and performance tracking
   - Verify database operations work correctly
7. **Monitoring**:
   - Provide deployment URL
   - Run `vercel logs` to stream real-time function logs
   - Show link to Vercel Dashboard for monitoring

## Success Criteria
- Deployment URL is generated and accessible
- Next.js frontend loads with all 4 tabs (Dashboard, Trades, Performance, Learning)
- FastAPI backend responds to all health checks
- All AI agents work correctly with streaming updates
- Trade database operations function properly
- Performance tracking displays correctly
- Environment variables are properly loaded

## Notes
- Single-stack architecture eliminates complexity
- All Streamlit features enhanced and migrated to Next.js
- FastAPI handles the complete AI agent system with learning
- Next.js provides responsive, modern UI
- StreamingResponse enables real-time agent updates
- SQLite database for trade storage and analytics
