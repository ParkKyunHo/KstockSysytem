import { Tile } from '@carbon/react';

interface PlaceholderPageProps {
  title: string;
  /**
   * Phase that will fill this in (e.g. "P5.3"). Surfaced so the user
   * sees explicitly which page is still a stub.
   */
  phase: string;
  /**
   * One-line description of what the page will do once implemented.
   */
  description: string;
}

/**
 * Phase 5 P5.2 routes render this stub. The real page wires the
 * design from frontend-prototype/ + backend API in P5.3+.
 */
export function PlaceholderPage({
  title,
  phase,
  description,
}: PlaceholderPageProps) {
  return (
    <>
      <header className="page-header">
        <h1 className="page-header__title">{title}</h1>
      </header>
      <Tile className="placeholder-tile">
        <p>{phase} 단계에서 이 화면이 구현됩니다.</p>
        <p className="placeholder-tile__hint">{description}</p>
      </Tile>
    </>
  );
}
