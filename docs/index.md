# 📁 Documentation Index

## 📚 Documentation Hub

This directory contains documentation for the Trading Control platform, including the unified stock/options agent architecture.

---

## **🎯 Main Documentation**

### **[README.md](../README.md)**
- **Purpose**: Main project documentation and quick-start guide
- **Content**: Architecture overview, endpoint map, setup instructions
- **Audience**: All users and developers

---

## **🏗️ Core Architecture**

### **[architecture.md](architecture.md)**
- **Purpose**: Current backend/frontend architecture and service boundaries
- **Content**: Stock + options multi-agent flows, route families, persistence model, env config
- **Audience**: Developers and technical architects

### **[development-guide.md](development-guide.md)**
- **Purpose**: Development setup and day-to-day workflow
- **Content**: Installation, configuration, testing, troubleshooting
- **Audience**: New developers and setup teams

---

## **🚀 Deployment & Production**

### **[deployment-guide.md](deployment-guide.md)**
- **Purpose**: Deployment instructions for different environments

### **[vercel-checklist.md](vercel-checklist.md)**
- **Purpose**: Step-by-step Vercel deployment checklist

### **[production-audit.md](production-audit.md)**
- **Purpose**: Production readiness and improvement tracking

### **[production-deployment-guide.md](production-deployment-guide.md)**
- **Purpose**: Production deployment best practices

---

## **🤝 Development & Testing**

### **[contributing.md](contributing.md)**
- **Purpose**: Contribution workflow and standards

### **[testing.md](testing.md)**
- **Purpose**: Testing strategy, tools, and conventions

---

## **📋 Quick Navigation**

### For API Consumers
1. Read [README.md](../README.md#api-endpoints)
2. Review options route family in [architecture.md](architecture.md#options-route-family)

### For Backend Developers
1. Read [architecture.md](architecture.md)
2. Follow [development-guide.md](development-guide.md)
3. Validate with [testing.md](testing.md)

### For Deployment Teams
1. Use [deployment-guide.md](deployment-guide.md)
2. Follow [vercel-checklist.md](vercel-checklist.md)

---

## **🔄 Maintenance Notes**

Keep docs current when any of these change:

- route contracts (especially `/api/options/*` parity endpoints)
- service responsibilities (`api/services/*`)
- environment variables (model/provider/tool configuration)
- persistence and observability behavior (`agent_runs`, performance metrics)
