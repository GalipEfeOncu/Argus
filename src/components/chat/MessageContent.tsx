import React from 'react';

interface MessageContentProps {
  content: string;
}

/**
 * A deliberately small, safe markdown treatment for chat text. Model output
 * is untrusted, so this renders text nodes rather than injecting HTML while
 * still making the common bold, italic, and inline-code forms readable.
 */
export const MessageContent: React.FC<MessageContentProps> = ({ content }) => {
  const blocks = content.split(/\n{2,}/);
  return (
    <div className="chat-message-content">
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n');
        return (
          <p key={`block-${blockIndex}`}>
            {lines.map((line, lineIndex) => (
              <React.Fragment key={`line-${lineIndex}`}>
                {renderInline(line)}
                {lineIndex < lines.length - 1 && <br />}
              </React.Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
};

function renderInline(value: string): React.ReactNode[] {
  const tokens = value.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g);
  return tokens.map((token, index) => {
    if (token.startsWith('**') && token.endsWith('**')) {
      return <strong key={`strong-${index}`}>{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={`code-${index}`}>{token.slice(1, -1)}</code>;
    }
    if (token.startsWith('*') && token.endsWith('*')) {
      return <em key={`em-${index}`}>{token.slice(1, -1)}</em>;
    }
    return token;
  });
}
