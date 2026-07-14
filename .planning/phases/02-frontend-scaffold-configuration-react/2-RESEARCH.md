# Phase 2: Frontend Scaffold & Configuration (React) - Research

**Researched:** 2025-05-24
**Domain:** React Frontend Development / UX Design / API Integration
**Confidence:** HIGH

## Summary

This research establishes the technical foundation for the Indexcards OCR frontend. We will move away from the generic dark-mode prototype toward a high-fidelity "Museum/Archive" aesthetic using modern React patterns. The stack is centered around Vite, React, TypeScript, and Tailwind CSS, with Zustand for state management and TanStack Query for server synchronization.

**Primary recommendation:** Use a "Parchment/Archive" theme with serif typography and subtle paper textures to create an immersive tool that feels native to the GLAM (Galleries, Libraries, Archives, and Museums) environment.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Upload UX:** List View for large file batches.
- **File Management:** Confirmation for deletions; unsupported formats marked visually; large files trigger Toasts.
- **Metadata:** Show total count and cumulative file size (e.g., "150 Files | 450 MB").
- **Configuration UI:** Start with blank slate; "Collection Type" (template) dropdown to pre-populate.
- **Field Management:** Confirmation for field removal; explicit "Clarification Step" for custom fields.
- **Step Flow:** Explicit button click transitions (Upload -> Configure -> Processing); hard block if no fields active.
- **State Persistence:** Data must persist when navigating "Back".
- **Global Reset:** "Start Fresh" button always visible.
- **Aesthetic:** "Museum," "Archive," or "Old Paper" themed (textures, custom colors, serif fonts).
- **Interactions:** Creative freedom for confirmation effects (pulses, shadows) and toast positioning.
- **Stats:** Live footer stats for files/fields.

### Claude's Discretion
- Implementation of confirmation effects (pulses, shadows).
- Toast positioning (e.g., Bottom Right vs. Top Center).
- Specific color hex codes and font pairings for the "Museum" theme.

### Deferred Ideas (OUT OF SCOPE)
- *N/A (All discussed items prioritized for Phase 2 or current scope)*
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FR1 | Image Upload (Drag & Drop) | React Dropzone + Axios/TanStack Query mutation to `/api/v1/upload/`. |
| FR2 | Metadata Field Configuration | Zustand `useConfigStore` + TanStack Query for `/api/v1/templates/`. |
| NFR2 | Usability (Museum Aesthetic) | Tailwind custom theme with `Crimson Text` and parchment colors. |
| NFR3 | Local Deployment | Vite default dev server and build output for static serving. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vite | 5.x+ | Build Tool | Extremely fast HMR and optimized production builds. |
| React | 18.x+ | UI Framework | Industry standard, excellent ecosystem for complex state. |
| TypeScript | 5.x+ | Typing | Essential for catching API contract errors early. |
| Tailwind CSS | 3.4+ | Styling | Rapid UI development with utility classes. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|--------------|
| Zustand | 4.x+ | State Management | Lightweight alternative to Redux for wizard-like step state. |
| TanStack Query | 5.x+ | Server State | Managing API calls, caching, and loading states. |
| React Dropzone | 14.x+ | File Upload | Robust drag-and-drop handling for large file batches. |
| Lucide React | Latest | Icons | Clean, consistent, and tree-shakeable SVG icons. |
| Sonner | Latest | Notifications | Highly customizable toast library (alternative to react-hot-toast). |
| Axios | 1.x+ | HTTP Client | Better error handling and interceptors than native fetch. |

**Installation:**
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install tailwindcss postcss autoprefixer zustand @tanstack/react-query react-dropzone lucide-react sonner axios
npx tailwindcss init -p
```

## Architecture Patterns

### Recommended Project Structure
```
frontend/
├── src/
│   ├── api/             # TanStack Query hooks & Axios instances
│   ├── components/      # Reusable UI components (Button, Card, Input)
│   ├── features/        # Feature-specific components
│   │   ├── upload/      # File list, Dropzone
│   │   ├── configure/   # Field management, Template selector
│   │   └── processing/  # Progress bar, WS integration
│   ├── hooks/           # Global hooks (useWebSocket, usePersistence)
│   ├── layouts/         # Layout components (MainLayout, WizardLayout)
│   ├── store/           # Zustand stores (useWizardStore, useBatchStore)
│   ├── theme/           # Custom Tailwind extensions & paper textures
│   └── types/           # TypeScript interfaces (matching Backend schemas)
```

### Pattern 1: Wizard State Management (Zustand)
**What:** A centralized store to manage step navigation and data persistence across steps.
**When to use:** Multi-step workflows like Upload -> Configure -> Process.
**Example:**
```typescript
interface WizardState {
  step: 'upload' | 'configure' | 'processing' | 'results';
  sessionId: string | null;
  files: UploadedFile[];
  fields: MetadataField[];
  setStep: (step: WizardState['step']) => void;
  addFiles: (newFiles: File[]) => void;
  // ... actions
}
```

### Anti-Patterns to Avoid
- **Local State Overload:** Don't keep complex file lists in local component state if they need to persist when moving back/forth between steps.
- **WebSocket in Components:** Don't initialize WebSockets inside functional components without a stable ref or global store; use a dedicated hook or singleton manager.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File Drag & Drop | Custom event listeners | `react-dropzone` | Edge cases (folder drops, browser quirks) are handled. |
| Toasts | Custom animations/portals | `sonner` | Handles stacking, accessibility, and auto-dismiss. |
| Data Fetching | Manual `useEffect` + `fetch` | `TanStack Query` | Handles caching, loading/error states, and retries. |
| CSS Grid Layouts | Complex custom CSS | Tailwind Grid | Standardized, responsive, and easy to maintain. |

## Common Pitfalls

### Pitfall 1: Large Batch Memory Pressure
**What goes wrong:** Displaying 100+ high-res image previews simultaneously can crash the browser tab.
**How to avoid:** Use "List View" (as decided) and avoid rendering large image thumbnails until a specific file is selected. Use object URLs responsibly and revoke them.

### Pitfall 2: WebSocket Re-attachment
**What goes wrong:** User refreshes page during processing; connection is lost; progress bar resets to 0.
**How to avoid:** Ensure the backend supports "re-attach" (implemented in Phase 1) and the frontend attempts to reconnect to the `batch_id` stored in Zustand/LocalStorage.

### Pitfall 3: Case-Sensitive Filenames
**What goes wrong:** OS-specific filename handling (Windows vs Linux) causing duplicate detections.
**How to avoid:** Let the backend handle the final naming, but provide clear visual feedback in the frontend if a file with the same name is added to the batch.

## Code Examples

### Museum/Archive Aesthetic (Tailwind Config)
```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        parchment: {
          light: '#FDFCF0',
          DEFAULT: '#F5F2E0',
          dark: '#E8E4C9',
        },
        archive: {
          ink: '#2C2C2C',
          paper: '#F1EFE0',
          sepia: '#704214',
        }
      },
      fontFamily: {
        serif: ['"Crimson Text"', 'Georgia', 'serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
      backgroundImage: {
        'paper-texture': "url('/assets/paper-noise.png')",
      }
    },
  }
}
```

### WebSocket Progress Hook
```typescript
// Source: Inspired by Phase 1 ws_manager.py
export const useBatchProgress = (batchId: string | null) => {
  const updateProgress = useBatchStore((s) => s.updateProgress);

  useEffect(() => {
    if (!batchId) return;
    const ws = new WebSocket(`ws://${location.host}/api/v1/ws/task/${batchId}`);
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      updateProgress(data); // { current, total, percentage, status, ... }
    };

    return () => ws.close();
  }, [batchId]);
};
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Redux Boilerplate | Zustand / Signals | 2022-2023 | Much less code, better performance for UI state. |
| Create React App | Vite | 2021 | 10x faster development start-up. |
| Axios + useEffect | TanStack Query | 2020+ | Standardized server-state management. |

## Open Questions

1. **Local Storage Persistence**
   - What we know: Data must persist between steps.
   - What's unclear: Should data persist across browser refreshes (sessions)?
   - Recommendation: Use Zustand's `persist` middleware to save the state to `localStorage` for a better user experience in case of accidental reloads.

2. **Image Preview**
   - What we know: List view is the primary mode.
   - What's unclear: Do we need a "Lightbox" or "Quick Look" for individual cards?
   - Recommendation: Implement a simple hover-preview or small thumbnail in the list to help users identify cards.

## Sources

### Primary (HIGH confidence)
- [Official Vite Docs](https://vitejs.dev/) - Project initialization.
- [Tailwind CSS Docs](https://tailwindcss.com/docs) - Theme extension and utility patterns.
- [Zustand GitHub](https://github.com/pmndrs/zustand) - Persistence middleware and store patterns.
- [Project Backend Code](backend/app/api/api_v1/endpoints/) - API contract verification.

### Secondary (MEDIUM confidence)
- [Museum Archive Aesthetic Research](https://github.com/tailwindlabs/tailwindcss/discussions) - Community color palette discussions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Industry standard in 2024/2025.
- Architecture: HIGH - Standard feature-based structure for React.
- Pitfalls: MEDIUM - Based on common browser/web app limitations.

**Research date:** 2025-05-24
**Valid until:** 2025-06-24
