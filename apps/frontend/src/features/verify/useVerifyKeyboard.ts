import { useEffect } from 'react';

export interface VerifyKeyboardHandlers {
  onNextCard: () => void;
  onPrevCard: () => void;
  onMarkVerified: () => void;
  onAcceptProposal: () => void;
  // Esc is handled by EditableCell itself, not here
}

/**
 * Document-level keyboard shortcut hook for the verification cockpit.
 *
 * Attaches a single keydown listener at document level. The FIRST thing
 * the handler does is check whether a text input (textarea or input) has
 * focus — if so, ALL shortcuts are suppressed so curators can type freely
 * (Phase 9 research Pitfall 5 guard).
 *
 * Shortcuts (only when no edit is active):
 *   j / ArrowDown  — next card
 *   k / ArrowUp    — previous card
 *   v              — mark current field verified
 *   Enter          — accept active corrector proposal
 *   Esc            — handled by EditableCell itself; no global handler needed
 *
 * @param handlers  Stable callback object (use useCallback on callsites)
 * @param enabled   Pass false to disable all shortcuts (e.g. while cockpit is loading)
 */
export function useVerifyKeyboard(
  handlers: VerifyKeyboardHandlers,
  enabled: boolean
): void {
  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // CRITICAL TEXT-INPUT GUARD — FIRST check in the handler.
      // This prevents j/k/v/Enter shortcuts from firing while the curator
      // is typing in an EditableCell textarea or any other input.
      const active = document.activeElement;
      const isEditing =
        active instanceof HTMLTextAreaElement ||
        active instanceof HTMLInputElement;
      if (isEditing) return;

      switch (e.key) {
        case 'j':
        case 'ArrowDown':
          e.preventDefault();
          handlers.onNextCard();
          break;
        case 'k':
        case 'ArrowUp':
          e.preventDefault();
          handlers.onPrevCard();
          break;
        case 'v':
          e.preventDefault();
          handlers.onMarkVerified();
          break;
        case 'Enter':
          e.preventDefault();
          handlers.onAcceptProposal();
          break;
        // Esc: EditableCell handles it locally (exits edit mode); no global handler needed
        default:
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [
    enabled,
    handlers.onNextCard,
    handlers.onPrevCard,
    handlers.onMarkVerified,
    handlers.onAcceptProposal,
  ]);
}
