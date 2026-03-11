# /streamlit-deploy - Deploy Streamlit Dashboard

## Goal
Deploy the Streamlit trading dashboard to Streamlit Cloud with all original functionality preserved.

## Steps
1. **Validation**: Check if trade-dashboard/ has all required files
2. **Dependencies**: Verify streamlit>=1.28.0 is in requirements.txt
3. **Environment**: 
   - Verify .streamlit/secrets.toml has ANTHROPIC_API_KEY
   - Check environment variables are properly configured
4. **Git Status**: Ensure no sensitive files are committed
5. **Deployment**:
   - Push changes to GitHub
   - Go to share.streamlit.io
   - Connect repository
   - Select `trade-dashboard/app.py` as main file
   - Configure environment variables in Streamlit Cloud dashboard
6. **Verification**:
   - Test dashboard loads correctly
   - Verify AI agents initialize
   - Check all functionality works

## Success Criteria
- Streamlit dashboard accessible online
- All original features working
- AI agents functional
- No sensitive data exposed
