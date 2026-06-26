export interface ArcaneDisplayProps {
  /** Roman numeral or Arabic number, styled in large Playfair Display gold (#D4956A) */
  number?: string;
  /** Card name below the number */
  name?: string;
  /** Interpretation text, small white-ish */
  description?: string;
  /** Advice line, gold-tinted, separated by a hairline */
  advice?: string;
  /** Glass-pill eyebrow badge text */
  eyebrow?: string;
  /** Date text appended to eyebrow after " · " */
  date?: string;
}

export declare function ArcaneDisplay(props: ArcaneDisplayProps): JSX.Element;
