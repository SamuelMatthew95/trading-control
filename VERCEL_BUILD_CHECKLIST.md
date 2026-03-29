# 🚀 Vercel-Safe Build Checklist
## Trading Control Dashboard - React Error #321 Prevention

---

## ✅ **PRE-BUILD VALIDATION**

### 1. **React Version Consistency**
```bash
# Check React versions are identical
npm list react react-dom
# Should show: react@18.3.1 and react-dom@18.3.1

# Check for multiple React copies
find node_modules -name "react" -not -path "*/@types/*" -not -path "*/@babel/*" -not -path "*/dist/*"
# Should only show: node_modules/react
```

### 2. **Package.json Resolutions**
```json
{
  "resolutions": {
    "react": "18.3.1",
    "react-dom": "18.3.1"
  }
}
```

### 3. **Dynamic Exports Verification**
All dashboard pages MUST have:
```typescript
'use client'

export const dynamic = 'force-dynamic'

export default function Page() {
  return <Component />
}
```

**Checklist:**
- [ ] `/dashboard/page.tsx`
- [ ] `/dashboard/agents/page.tsx`
- [ ] `/dashboard/learning/page.tsx`
- [ ] `/dashboard/system/page.tsx`
- [ ] `/dashboard/trading/page.tsx`

---

## ✅ **HOOK SAFETY VALIDATION**

### 4. **Client-Side Only Components**
All components using hooks MUST be client-side:

**✅ APPROVED PATTERN:**
```typescript
'use client'

// Hook usage INSIDE component
export default function Component() {
  useGlobalWebSocket()
  useWebSocketEvents()
  return <div />
}
```

**❌ FORBIDDEN PATTERNS:**
```typescript
// ❌ NO top-level hook calls
useGlobalWebSocket() // <- ERROR

// ❌ NO conditional hooks
if (condition) {
  useEffect(() => {}) // <- ERROR
}
```

### 5. **Hook Location Audit**
**Safe Hook Locations:**
- [ ] `src/hooks/useGlobalWebSocket.ts` - ✅ Client-only wrapper
- [ ] `src/hooks/useWebSocketEvents.ts` - ✅ Used inside components
- [ ] `src/components/SimpleDashboardPage.tsx` - ✅ Dynamic import with ssr:false
- [ ] `src/components/DashboardPageWrapper.tsx` - ✅ Client-side detection

**Hook Usage Verification:**
- [ ] All hooks called inside functional components ✓
- [ ] No top-level hook calls ✓
- [ ] No conditional hook calls ✓

---

## ✅ **BUILD OPTIMIZATION**

### 6. **Next.js Configuration**
```javascript
// next.config.js
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  experimental: {
    forceSwcTransforms: true,
  },
  trailingSlash: false,
  generateEtags: false,
}
```

### 7. **Root Layout Dynamic Export**
```typescript
// src/app/layout.tsx
export const dynamic = 'force-dynamic'
```

---

## ✅ **WEBSOCKET INTEGRATION**

### 8. **Event-Driven Architecture**
**✅ Current Implementation:**
- `WebSocketManager` singleton (no hooks)
- `useGlobalWebSocket` - connection management only
- `useWebSocketEvents` - event handling inside components
- Custom events for store updates

**WebSocket Flow Verification:**
- [ ] Manager runs outside React context ✓
- [ ] Events dispatched via `window.dispatchEvent` ✓
- [ ] Store updates happen inside components ✓
- [ ] No direct `getState()` calls ✓

---

## ✅ **TESTING & DEBUGGING**

### 9. **Development Build Testing**
```bash
# Test with unminified errors
pnpm dev

# Clear caches before production build
rm -rf .next
pnpm build
```

### 10. **Production Build Verification**
```bash
# Full production build test
pnpm build

# Verify all routes are dynamic
grep -r "export const dynamic" src/app/dashboard/
```

---

## ✅ **DEPLOYMENT READINESS**

### 11. **CI/CD Pipeline Checks**
```bash
# Lint (zero warnings)
pnpm lint

# Type check
pnpm type-check

# Build
pnpm build

# Test
pnpm test
```

### 12. **Vercel Configuration**
```json
// vercel.json
{
  "buildCommand": "cd frontend && pnpm build",
  "outputDirectory": "frontend/.next",
  "framework": "nextjs"
}
```

---

## 🚨 **ERROR #321 TROUBLESHOOTING**

### **If Error #321 Occurs:**

1. **Immediate Actions:**
```bash
# Clear everything
rm -rf .next node_modules
pnpm install
pnpm build
```

2. **Check Bundle Analysis:**
```bash
# Analyze bundle for React duplicates
pnpm build --analyze
```

3. **Development Mode Debug:**
```bash
# Run dev server to see full error
pnpm dev
# Navigate to /dashboard/agents
# Check console for detailed error
```

4. **Common Causes:**
- Multiple React copies (check with `find node_modules`)
- Hook called outside component (check all custom hooks)
- Server/client bundle mismatch (check dynamic exports)
- Context provider issues (check WebSocketProvider)

---

## ✅ **FINAL DEPLOYMENT CHECKLIST**

### **Before Push:**
- [ ] React versions consistent (18.3.1)
- [ ] All dashboard pages have `'use client'`
- [ ] All dashboard pages have `export const dynamic = 'force-dynamic'`
- [ ] No top-level hook calls
- [ ] Lint passes with zero warnings
- [ ] Build completes successfully
- [ ] WebSocket events flow correctly

### **After Deployment:**
- [ ] Dashboard loads without #321 error
- [ ] Agent data displays via WebSocket
- [ ] All sections (/agents, /learning, etc.) work
- [ ] Real-time updates functional

---

## 🎯 **SUCCESS METRICS**

**✅ Deployment Success When:**
- Build time: < 2 minutes
- Bundle size: < 100KB per page
- First paint: < 2 seconds
- WebSocket connection: < 1 second
- No #321 errors in production

**🚀 Ready for Production!**
