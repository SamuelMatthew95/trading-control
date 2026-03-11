# 🚀 Vercel Production Deployment Checklist

## ✅ Pre-Deployment Checklist

### 1. Repository Setup
- [ ] Git repository is clean (no uncommitted changes)
- [ ] `.gitignore` excludes `node_modules`, `.env.local`, `.next`
- [ ] All required files are committed and pushed

### 2. Environment Variables
- [ ] Copy `.env.example` to `.env.local`
- [ ] Set `ANTHROPIC_API_KEY` in Vercel dashboard
- [ ] Configure optional variables:
  - [ ] `NEXT_PUBLIC_VERCEL_ANALYTICS_ID`
  - [ ] `NEXT_PUBLIC_VERCEL_SPEED_INSIGHTS_ID`
  - [ ] `ALPHA_VANTAGE_API_KEY` (if using market data)

### 3. Vercel Project Setup
- [ ] Connect GitHub repository to Vercel
- [ ] Set framework detection to "Next.js"
- [ ] Configure build settings:
  - **Build Command**: `cd frontend && npm run build`
  - **Output Directory**: `frontend/.next`
  - **Install Command**: `cd frontend && npm install`

## 🔧 Vercel Dashboard Configuration

### Environment Variables Mapping
```
Local (.env.local)          → Vercel Environment
─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY          → ANTHROPIC_API_KEY
NEXT_PUBLIC_APP_URL        → NEXT_PUBLIC_APP_URL
NODE_ENV                   → NODE_ENV (set to production)
DATABASE_URL               → DATABASE_URL
```

### Domain Configuration
1. **Custom Domain** (optional):
   - Go to Project Settings → Domains
   - Add custom domain (e.g., `trading.yourdomain.com`)
   - Configure DNS records as shown by Vercel

2. **Automatic HTTPS**:
   - Vercel automatically provisions SSL certificates
   - No additional configuration needed

## 🚀 Deployment Steps

### 1. Initial Deployment
```bash
# Install Vercel CLI (if not installed)
npm i -g vercel

# Login to Vercel
vercel login

# Deploy to production
vercel --prod
```

### 2. Environment Variable Setup
1. Go to Vercel Dashboard → Your Project → Settings → Environment Variables
2. Add required variables:
   ```
   ANTHROPIC_API_KEY=your_actual_key_here
   NODE_ENV=production
   ```
3. Set variable scopes:
   - Production, Preview, Development (as needed)

### 3. Post-Deployment Verification
- [ ] Application loads at provided URL
- [ ] API endpoints respond correctly (`/api/health`)
- [ ] AI agents initialize without errors
- [ ] Trade database operations work
- [ ] Real-time streaming functions properly

## 🔍 Troubleshooting Guide

### Common Issues & Solutions

#### 1. Build Failures
**Issue**: TypeScript errors during build
**Solution**: 
```bash
cd frontend && npm run build
# Fix any TypeScript errors shown
```

#### 2. API Function Timeouts
**Issue**: Functions timeout after 10 seconds
**Solution**: Increase timeout in `vercel.json`:
```json
{
  "functions": {
    "api/index.py": {
      "maxDuration": 30
    }
  }
}
```

#### 3. Environment Variables Not Loading
**Issue**: API keys not accessible in functions
**Solution**: 
- Ensure variables are set in Vercel dashboard
- Use `process.env.VARIABLE_NAME` in Python
- Restart deployment after adding variables

#### 4. CORS Errors
**Issue**: Frontend can't access API
**Solution**: Headers are already configured in `vercel.json`
- Verify API routes are working
- Check browser console for specific error messages

## 📊 Monitoring & Analytics

### 1. Vercel Analytics
- Enable in Project Settings → Analytics
- Monitor page views, user behavior
- Track performance metrics

### 2. Speed Insights
- Enable in Project Settings → Speed Insights
- Monitor Core Web Vitals
- Optimize loading performance

### 3. Function Logs
```bash
# View real-time logs
vercel logs

# View specific deployment logs
vercel logs --deployment-id <deployment-id>
```

## 🔒 Security Checklist

- [ ] API keys are stored in environment variables (not code)
- [ ] HTTPS is enforced (automatic on Vercel)
- [ ] Security headers are configured (in `vercel.json`)
- [ ] CORS is properly configured
- [ ] No sensitive data in client-side code

## 📱 Performance Optimization

### 1. Image Optimization
- Images are automatically optimized by Next.js
- Custom domains configured in `next.config.js`

### 2. Bundle Analysis
```bash
cd frontend && npm run build
npm run analyze  # If @next/bundle-analyzer is installed
```

### 3. Caching Strategy
- Static assets cached for 1 year
- API responses set to `no-store`
- Next.js automatic caching for pages

## 🔄 CI/CD Integration

### GitHub Actions (Optional)
Create `.github/workflows/deploy.yml`:
```yaml
name: Deploy to Vercel
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy to Vercel
        uses: amondnet/vercel-action@v25
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.ORG_ID }}
          vercel-project-id: ${{ secrets.PROJECT_ID }}
          vercel-args: '--prod'
```

## ✅ Production Go-Live Checklist

- [ ] All tests passing locally
- [ ] Environment variables configured
- [ ] Custom domain (if applicable) configured
- [ ] SSL certificate active (automatic)
- [ ] Analytics enabled
- [ ] Error monitoring set up
- [ ] Performance monitoring active
- [ ] Backup strategy documented

## 🎯 Success Metrics

Your deployment is successful when:
- ✅ Application loads within 3 seconds
- ✅ All API endpoints return 200 status
- ✅ AI agents process requests without errors
- ✅ Real-time updates work smoothly
- ✅ Mobile responsive design functions
- ✅ No console errors on page load

---

**Need Help?**
- Vercel Docs: https://vercel.com/docs
- Next.js Deployment: https://nextjs.org/docs/deployment
- Support: Use Vercel Dashboard → Support → Contact Support
