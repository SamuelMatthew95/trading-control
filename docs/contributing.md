# 🤝 Contributing to Trading Bot Brain

We love your contributions! This document provides guidelines for contributing to our AI-powered trading dashboard.

---

## 🚀 Getting Started

### **Prerequisites**
- Python 3.11+
- Node.js 18+
- PostgreSQL database (local or managed)
- Anthropic API key (for AI agents)

### **Development Setup**
```bash
# 1. Fork and clone
git clone https://github.com/your-username/trading-control-python.git
cd trading-control-python

# 2. Set up Python environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Set up frontend
cd frontend
npm install
cd ..

# 4. Configure environment
cp .env.example .env.local
# Edit .env.local with your settings

# 5. Initialize database
python scripts/init_db.py
```

---

## 🏗️ Project Architecture

### **Monorepo Structure**
```
trading-control-python/
├── api/           # FastAPI backend (Python)
├── frontend/       # Next.js frontend (TypeScript/React)
├── scripts/        # Utility and setup scripts
├── docs/          # Documentation
└── tests/          # Test suites
```

### **Key Patterns**
- **Serverless-First**: All backend code works on Vercel Functions
- **Async-First**: Database operations use async/await patterns
- **Type-Safe**: Pydantic models for all API endpoints
- **Stateless**: No local file storage, use managed PostgreSQL

---

## 🧠 AI Agent Development

### **Adding New Agents**
1. **Create Agent Class** in `multi_agent_orchestrator.py`
```python
class NewAgent(BaseAgent):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.name = "NEW_AGENT"
        self.system_prompt = "Your agent prompt here"
    
    async def analyze(self, signals: List[Dict]) -> Dict:
        # Implement your agent logic
        return {
            "decision": "LONG/SHORT/FLAT",
            "confidence": 0.85,
            "reasoning": "Your reasoning here"
        }
```

2. **Register Agent** in orchestrator
```python
# Add to MultiAgentOrchestrator.__init__
self.agents["NEW_AGENT"] = NewAgent(api_key)
```

3. **Add to Learning System**
```python
# Add to AgentLearningSystem.__init__
self.agent_performance["NEW_AGENT"] = {
    "total_calls": 0,
    "successful_calls": 0,
    "avg_response_time": 0,
    "accuracy_score": 0,
    "improvement_areas": []
}
```

### **Agent Guidelines**
- ✅ **Async Methods**: All agent methods must be async
- ✅ **Error Handling**: Graceful failure with fallback decisions
- ✅ **Performance Tracking**: Record timing and success rates
- ✅ **Consistent Format**: Return standardized decision objects

---

## 📊 Database Development

### **Adding New Models**
1. **Define SQLAlchemy Model**
```python
# In api/database.py or new models file
class NewModel(Base):
    __tablename__ = "new_table"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

2. **Create Pydantic Schema**
```python
# In api/index.py
class NewModelRequest(BaseModel):
    name: str = Field(..., description="Model name")
    
class NewModelResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
```

3. **Add API Endpoints**
```python
@app.post("/api/new-model")
async def create_new_model(model: NewModelRequest):
    async with get_async_session() as session:
        db_model = NewModel(name=model.name)
        session.add(db_model)
        await session.commit()
        return {"id": db_model.id}

@app.get("/api/new-models")
async def get_new_models():
    async with get_async_session() as session:
        result = await session.execute(select(NewModel))
        models = result.scalars().all()
        return {"models": models}
```

---

## 🎨 Frontend Development

### **Component Structure**
```
frontend/src/
├── components/      # Reusable React components
├── hooks/          # Custom React hooks
├── utils/           # Utility functions
├── types/           # TypeScript type definitions
└── pages/           # Next.js pages
```

### **Adding New Features**
1. **Create Component** with TypeScript
```typescript
// frontend/src/components/NewFeature.tsx
interface NewFeatureProps {
  data: TradeData;
  onUpdate: (data: TradeData) => void;
}

export const NewFeature: React.FC<NewFeatureProps> = ({ data, onUpdate }) => {
  return (
    <div className="new-feature">
      {/* Your component JSX */}
    </div>
  );
};
```

2. **Add API Hook**
```typescript
// frontend/src/hooks/useNewFeature.ts
export const useNewFeature = () => {
  const [data, setData] = useState<TradeData | null>(null);
  
  const updateData = useCallback(async (newData: TradeData) => {
    try {
      await axios.post('/api/new-feature', newData);
      setData(newData);
    } catch (error) {
      console.error('Failed to update data:', error);
    }
  }, []);
  
  return { data, updateData };
};
```

---

## 🧪 Testing

### **Python Tests**
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=api --cov-report=html

# Run specific test file
pytest tests/test_agents.py
```

### **Frontend Tests**
```bash
cd frontend

# Run unit tests
npm test

# Run E2E tests
npm run test:e2e

# Run with coverage
npm run test:coverage
```

### **Test Structure**
```
tests/
├── unit/           # Unit tests
├── integration/    # Integration tests
├── e2e/           # End-to-end tests
└── fixtures/       # Test data
```

---

## 📝 Code Style

### **Python**
- **Black**: `black .` for formatting
- **isort**: `isort .` for import sorting
- **flake8**: `flake8 .` for linting
- **mypy**: `mypy .` for type checking

### **TypeScript/JavaScript**
- **Prettier**: `npm run format` for formatting
- **ESLint**: `npm run lint` for linting
- **TypeScript**: Strict mode enabled

---

## 🚀 Deployment

### **Development**
```bash
# Start backend
python api/index.py

# Start frontend (new terminal)
cd frontend && npm run dev
```

### **Production**
```bash
# Deploy to Vercel
vercel --prod

# Deploy with preview
vercel
```

---

## 📋 Pull Request Process

### **Before Submitting**
- [ ] **Tests Pass**: All tests must pass
- [ ] **Code Style**: Follow project style guidelines
- [ ] **Documentation**: Update relevant documentation
- [ ] **Type Safety**: No TypeScript/Python type errors
- [ ] **Environment**: Works with provided `.env.example`

### **PR Template**
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
```

---

## 🏷️ Issue Reporting

### **Bug Reports**
Use this template for bug reports:
```markdown
**Description**: Clear description of the issue
**Steps to Reproduce**: 
1. Step one
2. Step two
3. Step three
**Expected Behavior**: What should happen
**Actual Behavior**: What actually happens
**Environment**: OS, browser, version
**Additional Context**: Any other relevant info
```

### **Feature Requests**
```markdown
**Problem**: What problem does this solve?
**Proposed Solution**: How should it work?
**Alternatives Considered**: What other approaches did you consider?
**Additional Context**: Any other relevant info
```

---

## 🎯 Development Guidelines

### **Principles**
1. **Serverless-First**: All code must work on Vercel Functions
2. **Async-First**: Use async/await for all I/O operations
3. **Type-Safe**: Use TypeScript and Pydantic for type safety
4. **Test-Driven**: Write tests before implementing features
5. **Documentation**: Keep docs updated with code changes

### **Performance**
- **Database**: Use connection pooling and proper indexing
- **Frontend**: Optimize bundle size and loading performance
- **API**: Implement proper caching strategies
- **AI Agents**: Track and optimize response times

### **Security**
- **Environment Variables**: Never commit secrets to git
- **Input Validation**: Validate all user inputs
- **SQL Injection**: Use parameterized queries only
- **CORS**: Properly configure for production domains

---

## 🤝 Community

### **Getting Help**
- **Discussions**: Use GitHub Discussions for questions
- **Issues**: Use GitHub Issues for bugs and features
- **Documentation**: Check docs before asking questions

### **Code of Conduct**
- Be respectful and inclusive
- Provide constructive feedback
- Help others learn and grow
- Follow the project's technical standards

---

## 🎉 Recognition

Contributors will be recognized in:
- **README.md**: Contributor list with links
- **Release Notes**: Mentioned in changelogs
- **Discord/Slack**: Special contributor roles
- **Swag**: Contributors may receive project swag

---

**Thank you for contributing to Trading Bot Brain!** 🚀

Together we're building the future of AI-powered trading systems.
