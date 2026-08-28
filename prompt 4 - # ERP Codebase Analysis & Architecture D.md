# ERP Codebase Analysis & Architecture Documentation

Thoroughly inspect and analyze the **entire project folder** before writing any documentation. Understand the ERP software from the actual implementation, including its frontend, backend, database, configuration, integrations, business logic, workflows, authentication, infrastructure, and supporting services.

Your documentation must be based **strictly on what actually exists in the project**.

**Do not invent functionality, components, services, APIs, databases, integrations, workflows, infrastructure, business rules, or architectural patterns.**

If something is unclear from the implementation, explicitly document the uncertainty instead of making an assumption.

## Output Files

Create/update **only** these two files in the project root:

1. `DOCUMENTATION.md`
2. `ARCHITECTURE.md`

**Do not modify application source code, configuration files, dependencies, database files, or any other project files.**

---

# Part 1 — `DOCUMENTATION.md`

Create a comprehensive technical reference for the ERP.

The documentation should be detailed enough that a developer who has never seen this project can understand, maintain, debug, extend, and deploy the system.

## 1. ERP Overview

Document:

* Overall purpose of the ERP
* Core business purpose
* Main users/personas if identifiable from the implementation
* Main business domains
* Major capabilities
* Overall application behavior
* Major workflows
* How the different modules work together

Only describe functionality that can be verified from the codebase.

---

## 2. Technology Stack

Identify the actual technologies used, including where applicable:

* Programming languages
* Frontend frameworks
* Backend frameworks
* UI libraries
* Build tools
* Package managers
* Database technology
* ORM/query builders
* Authentication libraries
* Validation libraries
* API technologies
* Caching technologies
* Queue/job technologies
* File-storage technologies
* Email providers
* Payment providers
* Cloud services
* External APIs
* Monitoring/logging tools
* Testing frameworks
* Deployment technologies

For each important technology, explain its actual purpose in this project.

Do not list technologies merely because they are common for the framework.

---

## 3. Complete Project Structure

Inspect the entire project tree and document the important directories and files.

Explain:

* Root-level files
* Frontend directories
* Backend directories
* API directories
* Components
* Pages
* Services
* Controllers
* Routes
* Models
* Database directories
* Migrations
* Configuration
* Utilities
* Middleware
* Jobs/workers
* Tests
* Scripts
* Assets
* Storage-related directories
* Deployment/infrastructure files

Use a table where useful:

| Path | Purpose | Important Contents |
| ---- | ------- | ------------------ |

Do not merely reproduce the directory tree. Explain what the important parts actually do.

---

## 4. Core Modules and Features

Identify all major ERP modules and features that actually exist.

For every major module, document:

* Purpose
* Main functionality
* Important pages/screens
* Frontend components
* Backend services
* Controllers/routes/APIs
* Database models/tables
* Important business rules
* Related permissions
* Related integrations
* Important source-code paths

Examples of domains should only be included if they actually exist, such as:

* Users
* Employees
* Customers
* Vendors
* Products
* Inventory
* Sales
* Purchasing
* Accounting
* HR
* Payroll
* Orders
* Invoices
* Payments
* Reporting
* Notifications
* Documents

Do not assume any of these exist.

---

# 5. Frontend Architecture

Document the actual frontend implementation.

Include:

* Frontend framework
* Application entry points
* Routing
* Pages
* Layouts
* Major modules
* Components
* Reusable UI components
* Forms
* Tables
* Dashboards
* State management
* API/client layer
* Authentication handling
* Authorization/UI permission handling
* Validation
* Error handling
* Loading states
* Notifications
* File uploads/downloads
* Export functionality
* Styling system
* Theme system if present

For important functionality, reference exact source paths and, where useful:

* Components
* Functions
* Hooks
* Classes
* Stores
* API clients
* Route definitions

Example:

`src/pages/orders/OrdersPage.tsx` — order listing page.

Do not invent paths; use paths actually found in the project.

---

# 6. Backend Architecture

Document the actual backend architecture.

Include, where applicable:

* Application entry point
* Framework
* Routing
* Controllers
* API endpoints
* Middleware
* Authentication middleware
* Authorization middleware
* Services
* Business logic
* Repositories
* Utilities
* Validation
* Serialization
* Error handling
* Logging
* Background processing
* External service clients
* File handling

Explain how a typical request travels through the backend.

For important endpoints, document:

| Method | Route | Controller/Handler | Service | Purpose | Authentication |
| ------ | ----- | ------------------ | ------- | ------- | -------------- |

Use actual routes and implementation names discovered in the project.

---

# 7. Database Architecture

Inspect the actual database implementation.

Document:

* Database technology
* ORM/query layer
* Tables
* Models/entities
* Fields
* Primary keys
* Foreign keys
* Relationships
* Indexes where important
* Constraints
* Enums
* Join/pivot tables
* Soft deletes
* Audit fields
* Migrations
* Seeders
* Database initialization

Explain important relationships between business domains.

For important models, include the actual source file path.

Do not invent fields or relationships.

---

# 8. Authentication, Authorization, Roles, and Permissions

Document the actual security implementation.

Include:

* Login/authentication mechanism
* Sessions/tokens/JWT/etc.
* Password handling
* Authentication middleware
* Authorization middleware
* Roles
* Permissions
* Permission checks
* User-role relationships
* Role-permission relationships
* Frontend permission handling
* Protected routes
* API authorization
* Account/security flows

Explain the actual authentication and authorization flow.

Never expose passwords, tokens, API keys, secrets, or credentials.

---

# 9. Integrations and External Services

Identify every actual external integration found in the project.

For each integration document:

* Service/provider
* Purpose
* API/client implementation
* Configuration variables
* Authentication mechanism without exposing secrets
* Data exchanged
* Relevant source files
* Where it is used

Only document integrations that actually exist.

---

# 10. Environment Variables and Configuration

Inspect configuration files and environment-variable usage.

Document:

| Variable | Purpose | Required/Optional | Used By |
| -------- | ------- | ----------------- | ------- |

**Never include secret values.**

Do not print:

* Passwords
* API keys
* Access tokens
* Private keys
* Connection secrets
* Credentials
* Session secrets

Only document variable names and their purposes.

---

# 11. Dependencies

Identify important project dependencies.

For each significant dependency explain:

* Name
* Version if useful
* Purpose
* Where it is used

Focus on dependencies that materially affect the architecture or functionality.

---

# 12. Data Flow

Document how data moves through the system.

Explain actual flows such as:

```text
User
  ↓
Frontend Page
  ↓
Frontend API Client
  ↓
Backend Route
  ↓
Controller
  ↓
Service / Business Logic
  ↓
Model / Repository
  ↓
Database
```

Only include layers that actually exist.

Also document important flows involving:

* External APIs
* File storage
* Email
* Notifications
* Background jobs
* Queues
* Workers
* Scheduled tasks

---

# 13. Business Rules and Validation

Identify important business rules implemented in code.

Document:

* Validation rules
* State transitions
* Calculation rules
* Approval workflows
* Status changes
* Permission-dependent behavior
* Data consistency rules
* Required relationships
* Important constraints
* Domain-specific calculations

For each important rule, reference the relevant source file/function/class.

Do not infer business rules that are not implemented.

---

# 14. Background Jobs, Queues, Workers, and Automation

Identify actual:

* Background jobs
* Queues
* Workers
* Scheduled tasks
* Cron jobs
* Event handlers
* Consumers
* Automated workflows
* Recurring processes

For each one document:

* Trigger
* Processing flow
* Purpose
* Related files
* External systems involved
* Failure/retry behavior if implemented

---

# 15. File Storage and Document Handling

Document actual file/document functionality.

Include:

* Uploads
* Downloads
* File storage
* Storage providers
* Document records
* File metadata
* File validation
* File processing
* Attachments
* Generated documents
* Import/export files

Identify the relevant source-code paths.

---

# 16. Reporting, Dashboards, Notifications, and Exports

Document actual implementations of:

* Dashboards
* Reports
* Analytics
* Charts
* PDF generation
* CSV/Excel exports
* Data exports
* Email notifications
* In-app notifications
* Push notifications
* Alerts

Explain their data sources and implementation.

---

# 17. Error Handling and Logging

Document:

* Global error handling
* API error responses
* Validation errors
* Exception handling
* Logging
* Audit logging
* Error reporting
* Frontend error handling
* Backend error handling
* Retry mechanisms

Reference relevant source files where appropriate.

---

# 18. Deployment and Build Configuration

Inspect and document actual deployment/build configuration.

Include:

* Build commands
* Development commands
* Production commands
* Package scripts
* Docker configuration
* Docker Compose
* CI/CD
* Hosting configuration
* Environment configuration
* Web server configuration
* Database deployment/migrations
* Asset builds
* Production startup

Do not invent deployment infrastructure that is not present.

---

# 19. Scripts and Commands

Document important commands from the project configuration.

Include:

* Install
* Development
* Build
* Production
* Test
* Lint
* Format
* Database migration
* Database seed
* Worker startup
* Other important scripts

Only document commands that actually exist or can be directly verified.

---

# 20. Testing

Inspect the test structure.

Document:

* Testing frameworks
* Unit tests
* Integration tests
* API tests
* End-to-end tests
* Component tests
* Test directories
* Test setup
* Fixtures
* Factories
* Mocks
* Important tested workflows
* Test commands

Clearly distinguish between functionality that is tested and functionality for which no tests were found.

---

# 21. Architectural Decisions and Conventions

Document important architectural patterns actually present in the code.

Examples may include:

* Layered architecture
* MVC
* Service layer
* Repository pattern
* Modular architecture
* Monolith
* Microservices
* REST
* GraphQL
* Event-driven patterns
* Shared components
* State management conventions

Only identify patterns when supported by the implementation.

Explain important conventions another developer should follow.

---

# 22. Known Limitations, TODOs, and Incomplete Areas

Search the project for actual:

* TODOs
* FIXMEs
* Not implemented sections
* Placeholder functionality
* Disabled features
* Dead/incomplete flows
* Known limitations
* Missing tests
* Configuration limitations
* Technical debt

Clearly distinguish confirmed limitations from uncertainty.

---

# 23. Source-Code References

Throughout `DOCUMENTATION.md`, reference important implementation files.

Where useful include:

* File paths
* Classes
* Functions
* Components
* Controllers
* Services
* Models
* Routes
* API endpoints
* Migration names

References must point to files that actually exist.

---

# Part 2 — `ARCHITECTURE.md`

Create a separate technical architecture document for the ERP.

The architecture documentation must be based strictly on the actual implementation discovered during the project analysis.

---

# 24. Architecture Overview

Explain:

* Overall architecture style
* Major applications
* Frontend
* Backend
* Database
* Storage
* External services
* Background processing
* Infrastructure
* Major communication paths

Clearly distinguish actual architectural components from conceptual boundaries used only for explanation.

---

# 25. Complete System Architecture Diagram

Create a **complete high-level Mermaid system architecture diagram**.

At minimum, show:

```text
Frontend
   ↓
API / Backend
   ↓
Business Logic / Services
   ↓
Database
```

Add other components only if they actually exist.

The diagram should represent, where applicable:

* Frontend applications
* Major frontend layers
* Pages/modules
* Major UI/application components
* Frontend-to-backend communication
* Backend application
* Backend services/modules
* API routes/controllers/endpoints
* Authentication
* Authorization
* Business/service layers
* Database
* Major models/tables
* Important domain relationships
* File/document storage
* Background jobs
* Queues
* Workers
* Scheduled tasks
* External APIs
* Third-party integrations
* Email services
* Notification services
* Payment services
* Caching
* Infrastructure components
* Configuration-dependent services
* Major data flows

Use actual component names from the codebase whenever identifiable.

---

# 26. Mermaid Diagram Accuracy Rules

Every Mermaid diagram must satisfy these rules:

### Strict implementation accuracy

Base every diagram strictly on the implementation.

**Do not invent:**

* Services
* APIs
* Databases
* Tables
* Queues
* Workers
* Caches
* Cloud services
* Integrations
* Payment systems
* Email providers
* Authentication providers
* Workflows
* Microservices

Do not add generic ERP architecture components simply because they are common.

### Actual names

Where possible, use actual names of:

* Applications
* Modules
* Services
* Controllers
* Routes
* APIs
* Models
* Databases
* Integrations

### Uncertainty

If implementation details are unclear:

* Do not guess.
* Do not represent assumptions as facts.
* Document the uncertainty in the surrounding text.

### Traceability

Cross-reference important diagram components with their source-code paths.

For example:

```text
Order API
→ backend/routes/orders.ts
→ backend/controllers/OrderController.ts
→ backend/services/OrderService.ts
```

Use actual paths from the project.

---

# 27. Additional Mermaid Diagrams

Where meaningful and supported by the implementation, include separate diagrams rather than forcing everything into one enormous diagram.

Potential diagrams include:

## System / Component Architecture

Use a Mermaid `flowchart` to show major components and their relationships.

## Frontend → API → Backend Data Flow

Show the actual request/data path from:

```text
Frontend component
→ API client
→ Route
→ Controller
→ Service
→ Database
```

Only include layers that actually exist.

## Authentication / Authorization Flow

Show the actual:

```text
User
→ Login
→ Authentication
→ Token/session
→ Authorization
→ Protected resource
```

Only if this flow exists.

## Database Entity Relationships

Use Mermaid `erDiagram` to show important actual models/tables and relationships.

Do not attempt to include every database table if doing so would make the diagram unreadable. Focus on important business domains while documenting the complete schema separately in `DOCUMENTATION.md`.

## Important Business Workflows

Where useful, use Mermaid `flowchart` or `sequenceDiagram` for important workflows such as:

* Order processing
* Approval workflows
* Inventory movement
* Invoice processing
* Payment processing
* Employee workflows
* Document processing
* Notifications

Only include workflows that actually exist.

## External Integration Flow

Where applicable, show communication between the ERP and actual external systems.

---

# 28. Backend API / Route Mapping

Create a clear mapping of actual API routes.

Use a table such as:

| Method | Route | Controller/Handler | Service | Authentication | Purpose |
| ------ | ----- | ------------------ | ------- | -------------- | ------- |

Only include endpoints that can be verified from the project.

---

# 29. Frontend-to-Backend Mapping

Where useful, document:

| Frontend Page/Component | API | Backend Handler | Business Service | Database Model |
| ----------------------- | --- | --------------- | ---------------- | -------------- |

This should help a developer trace functionality from UI to database.

---

# 30. Database Architecture

Summarize the database architecture in `ARCHITECTURE.md`.

Include:

* Database technology
* Main domain models
* Important relationships
* Data ownership boundaries
* Important persistence flows

Include an `erDiagram` when meaningful.

---

# 31. Authentication and Authorization Architecture

Document the actual security architecture.

Include:

* Authentication mechanism
* Session/token flow
* Middleware
* Roles
* Permissions
* Protected frontend routes
* Protected backend endpoints
* Authorization checks

Include a Mermaid authentication flow if useful.

---

# 32. External Integrations

Document actual third-party integrations and show their relationship with the ERP.

For each integration identify:

* ERP component using it
* External service
* Communication mechanism
* Data exchanged
* Configuration variables
* Failure handling if implemented

---

# 33. Background Processing Architecture

If background jobs, queues, workers, scheduled tasks, or automation exist, document:

* Trigger
* Queue
* Worker
* Processing logic
* Database interaction
* External services

Create a Mermaid diagram if it adds meaningful clarity.

If no such infrastructure exists, explicitly state that no background processing infrastructure was found rather than inventing one.

---

# 34. Deployment / Infrastructure Architecture

If deployment configuration exists, document the actual production/development architecture.

Include only infrastructure verifiable from:

* Dockerfiles
* Docker Compose
* CI/CD configuration
* Deployment scripts
* Cloud configuration
* Server configuration
* Package scripts
* Infrastructure files

Do not invent hosting infrastructure.

---

# 35. Architecture Constraints and Security Considerations

Document actual:

* Environment dependencies
* Configuration requirements
* Security boundaries
* Role boundaries
* External service dependencies
* Deployment constraints
* Database constraints
* Architectural limitations
* Technical debt

Never expose secrets.

---

# 36. Architecture-to-Source Traceability

End `ARCHITECTURE.md` with a useful mapping such as:

| Architecture Component | Source Path(s) | Responsibility        |
| ---------------------- | -------------- | --------------------- |
| Frontend application   | actual path    | actual responsibility |
| API layer              | actual path    | actual responsibility |
| Authentication         | actual path    | actual responsibility |
| Business service       | actual path    | actual responsibility |
| Database models        | actual path    | actual responsibility |
| Storage                | actual path    | actual responsibility |
| Background processing  | actual path    | actual responsibility |

Only use paths that actually exist.

---

# Critical Accuracy Requirements

These rules apply to **both files**.

1. **Inspect the entire project before documenting it.**

2. Do not rely on assumptions based on the name of the project or typical ERP architecture.

3. Do not invent functionality.

4. Do not invent APIs.

5. Do not invent database tables or relationships.

6. Do not invent integrations.

7. Do not invent infrastructure.

8. Do not invent queues, workers, caches, or scheduled jobs.

9. Do not invent authentication or authorization behavior.

10. Do not claim something exists merely because the framework supports it.

11. If functionality is present but incomplete, document it as incomplete.

12. If functionality appears referenced but its implementation cannot be confirmed, explicitly state the uncertainty.

13. Prefer exact source-code references over generic descriptions.

14. Use actual class, function, component, route, service, and model names when identifiable.

15. Never include secret values.

16. Never include passwords, tokens, API keys, private keys, connection-string secrets, or credentials.

17. Do not modify application source code.

18. Do not modify application configuration files.

19. Do not modify dependencies.

20. Only create or update:

* `DOCUMENTATION.md`
* `ARCHITECTURE.md`

---

# Documentation Quality Requirements

The final documentation should be:

* Accurate
* Implementation-driven
* Developer-oriented
* Comprehensive
* Well organized
* Easy to navigate
* Explicit about uncertainty
* Traceable to source code
* Free of invented functionality

Use:

* Markdown headings
* Tables
* Bullet lists
* Code blocks where useful
* Mermaid diagrams
* Source-code paths
* Class/function/component names

Avoid generic explanations of technologies that do not help explain this particular ERP.

The objective is not to produce generic ERP documentation.

The objective is to produce a **faithful technical map of this exact codebase** so that another developer can understand how the system is implemented, how its components communicate, where important business logic lives, how data flows through the system, and how to maintain or extend it safely.
