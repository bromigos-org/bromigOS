// An address the board doesn't have: every page of the board is "/" and its hash.
export default function NotFound() {
  return (
    <div className="unreach">
      <h1>Nothing here</h1>
      <p>
        <a href="/" title="Open the Lab board">
          Open the Lab board
        </a>
      </p>
    </div>
  );
}
