import { ReactNode } from 'react';

export interface PhotoCardProps {
  /** Background image URL. Omit to use the default dark-earth gradient. */
  imageUrl?: string;
  /** Glass-pill eyebrow badge text, e.g. "Личный центр" */
  eyebrow?: string;
  /** Main heading text (rendered in Playfair Display serif, white) */
  title?: string;
  /** Italic accent word appended to title, styled in terra (#D4956A) */
  titleEm?: string;
  /** Subtitle below heading, small white muted text */
  subtitle?: string;
  /**
   * Overlay gradient direction:
   *  - "default" — bottom-up dark (hero greeting, tarot hero)
   *  - "diagonal" — angled (matrix card)
   *  - "side" — left-to-right (wide practice card)
   * @default "default"
   */
  overlay?: 'default' | 'diagonal' | 'side';
  /** Minimum height in pixels @default 256 */
  minHeight?: number;
  /** Content rendered inside photo-card-body below title/subtitle */
  children?: ReactNode;
}

export declare function PhotoCard(props: PhotoCardProps): JSX.Element;
