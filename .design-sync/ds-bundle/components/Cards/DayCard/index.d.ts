export interface DayCardProps {
  /** Symbol or emoji shown in the terra-tinted square, e.g. "☀", "✦", "🌙" */
  symbol?: string;
  /** Card name in Playfair Display serif, e.g. "Солнце" */
  name: string;
  /** Short phrase below the name */
  phrase?: string;
  /** Small label above the name @default "Аркан дня" */
  label?: string;
  /** Optional navigation href — wraps the card in an anchor */
  href?: string;
}

export declare function DayCard(props: DayCardProps): JSX.Element;
