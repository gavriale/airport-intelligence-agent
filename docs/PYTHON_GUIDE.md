# Python guide for this project (for me)

This guide explains the Python in this repo. The examples come from the project's real code. Some are shortened to show the idea. A `# file/path.py` comment shows where a snippet lives.

Rules I used: simple words, short sentences, at most 3 bullets per idea.

**Contents**
1. [Files and imports](#1-files-and-imports)
2. [Basic syntax you see everywhere](#2-basic-syntax-you-see-everywhere)
3. [Types (the `: str` things)](#3-types-the--str-things)
4. [Functions](#4-functions)
5. [Classes](#5-classes)
6. [BaseModel (pydantic)](#6-basemodel-pydantic)
7. [Protocol, dataclass and other class helpers](#7-protocol-dataclass-and-other-class-helpers)
8. [Decorators (the `@` lines)](#8-decorators-the--lines)
9. [async and await](#9-async-and-await)
10. [Errors and exceptions](#10-errors-and-exceptions)
11. [Collections and loops](#11-collections-and-loops)
12. [Other things you will meet](#12-other-things-you-will-meet)
13. [Tests (pytest)](#13-tests-pytest)
14. [Tools and project files](#14-tools-and-project-files)
15. [How to read an error message](#15-how-to-read-an-error-message)
16. [Worked example: MemorySessionStore and interfaces](#16-worked-example-memorysessionstore-and-interfaces)
17. [Worked example: container.py (the builder)](#17-worked-example-containerpy-the-builder)
18. [Worked example: agent.py (the brain)](#18-worked-example-agentpy-the-brain)
19. [Worked example: tools](#19-worked-example-tools)
20. [How the model chooses tools (and where the loop is)](#20-how-the-model-chooses-tools-and-where-the-loop-is)

---

## 1. Files and imports

### A file is a module
Every `.py` file is a "module". A folder with an `__init__.py` file is a "package".
- `core/agent.py` is the module `core.agent`.
- The `__init__.py` files in this repo are empty. They only mark the folder as a package.
- Python finds modules starting from the folder where you run it (the project root).

### import
```python
# core/agent.py
import asyncio
from pydantic import BaseModel
from core.errors import LLMError, PolicyViolation
```
- `import asyncio` loads the whole module. You write `asyncio.sleep(...)`.
- `from X import Y` takes one name out of a module. You write `Y` directly.
- `core.errors` means the file `core/errors.py`.

### import ... as ...
```python
from core.logging import session_id as session_id_var
```
- `as` gives the name a different name.
- Here it avoids a clash with a function argument also called `session_id`.

### Docstring
```python
"""Tool registry: schemas, validation, and the code-level gates in front of every handler."""
```
- A string in triple quotes at the top of a file, class or function is a docstring.
- It is documentation. It does not run.
- VS Code shows it when you hover over the name.

### `if __name__ == "__main__":`
```python
# cli.py
if __name__ == "__main__":
    asyncio.run(main())
```
- When you run a file directly, Python sets `__name__` to `"__main__"`.
- When another file imports it, `__name__` is the module name instead.
- So this line means: "run this only when started directly".

### `__file__` and `Path`
```python
# app/container.py
DOMAIN_DIR = Path(__file__).resolve().parent.parent / "domain"
```
- `__file__` is the path of the current file.
- `.parent` goes up one folder. The `/` joins path parts.
- `Path` comes from `pathlib`. It works the same on Windows and Linux.

### Why `core/logging.py` does not break the real `logging`
- Inside `core/logging.py`, `import logging` gets the standard library one.
- Python 3 uses full paths, so `core.logging` and `logging` are different names.
- Only run files from the project root so paths stay correct.

---

## 2. Basic syntax you see everywhere

### Indentation is the structure
```python
if session.escalated:
    return self._finish(...)
```
- Python has no `{ }`. The indented lines are the block.
- Use 4 spaces. Never mix tabs and spaces.
- A line ending with `:` starts a block.

### Comments
```python
# This is a comment
x = 5  # also a comment
```
- `#` starts a comment until the end of the line.
- There are no multi-line comments. Use several `#` lines.

### Variables need no keyword
```python
started = time.perf_counter()
```
- No `let`, `var` or `const`.
- A name is created the first time you assign to it.
- `UPPER_CASE` names (like `MAX_ITERATIONS`) are constants by habit only. Python does not enforce it.

### None, True, False
```python
verified_customer_id: str | None = None
```
- `None` means "no value". It is like `null`.
- Check it with `is None` or `is not None`. Do not use `==`.
- `True` and `False` start with a capital letter.

### Truthy and falsy
```python
if not message:
    return
```
- Empty things count as False: `""`, `[]`, `{}`, `0`, `None`.
- Everything else counts as True.
- So `if items:` means "if the list is not empty".

### `or` and `and` return values
```python
llm = llm or AnthropicLLM(...)
```
- `a or b` gives `a` if `a` is truthy, else `b`.
- This is a short way to say "use a default".
- `and` works the other way: it stops at the first falsy value.

### Ternary (one-line if)
```python
# adapters/bm25_index.py
title = text.splitlines()[0].lstrip("# ").strip() if text else path.stem
```
- Format: `value_if_true if condition else value_if_false`.
- The condition is in the middle.

### f-strings
```python
f"{_relative_path(record.pathname)}:{record.lineno}"
f"LLM failed after {attempt + 1} attempts: {exc!r}"
```
- A string that starts with `f` can hold code in `{ }`.
- `{x!r}` shows the "repr" of x. It adds quotes and shows the type clearly. Good for errors.
- `{x:.0f}` formats a number with 0 decimals.

### `_` as a name
```python
for _ in range(self._max_iterations):
```
- `_` means "I do not need this value".
- The loop just repeats N times.

### Leading underscore
```python
self._llm = llm
def _call_llm(...)
class _TurnStats: ...
```
- A name that starts with `_` means "private, for use inside this class or file".
- Python does not block you from using it. It is a signal to humans.
- A name with double underscores on both sides, like `__init__`, is a special name Python knows. These are called "dunder" methods.

### `assert`
```python
raise AssertionError("unreachable")
```
- This marks a line that should never run.
- If it does run, something is wrong in the code. It crashes loudly.

### `# noqa`
```python
except Exception:  # noqa: BLE001 - the loop must survive any handler bug
```
- It tells the linter (`ruff`) to ignore a rule on this line.
- The text after the code explains why. I wrote the reason each time.

---

## 3. Types (the `: str` things)

### Type hints
```python
def run_turn(self, session_id: str, user_text: str) -> TurnResult:
```
- `session_id: str` says the argument should be a string.
- `-> TurnResult` says what the function returns.
- Python does NOT check these when running. Tools like VS Code and `pydantic` use them.

### Union with `|`
```python
verified_customer_id: str | None = None
```
- `str | None` means "a string or None".
- It reads as "or".
- Older code writes `Optional[str]`. Same meaning.

### Generic types
```python
messages: list[Message]
arguments: dict[str, Any]
```
- `list[Message]` is a list that holds `Message` objects.
- `dict[str, Any]` is a dictionary with string keys and any values.
- `Any` means "no rule about the type".

### Literal
```python
role: Literal["user", "assistant"]
access: Literal["read", "write"] = "read"
```
- The value must be exactly one of the listed values.
- It is like a small enum written inline.

### Callable and Awaitable
```python
Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]
```
- `Callable[[A, B], R]` is "a function that takes A and B and returns R".
- `Awaitable[R]` means the function is `async` and gives back R after `await`.
- `Handler = ...` gives that long type a short name.

### `type[BaseModel]`
```python
input_model: type[BaseModel]
```
- This is the class itself, not an object of the class.
- It lets us pass `VerifyIdentityArgs` (the class) as a value.
- Later the code calls `input_model.model_validate(...)` on it.

### TYPE_CHECKING
```python
# core/interfaces.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session import Session
```
- `TYPE_CHECKING` is False at runtime, True for the editor.
- It lets us import a name only for type hints.
- This avoids a circular import: `session.py` imports `interfaces.py`, and `interfaces.py` wants `Session` for hints only.

---

## 4. Functions

### def
```python
def _ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000
```
- `def name(args):` defines a function.
- `return` gives a value back. No return means `None`.
- The `*` is multiply. `**` is power.

### Default values and keyword arguments
```python
def __init__(self, llm, sessions, *, llm_timeout_s: float, max_iterations: int = 6): ...

Agent(llm, sessions, llm_timeout_s=30)
```
- `max_iterations: int = 6` has a default. You may skip it.
- You can pass by name: `llm_timeout_s=30`.
- A lone `*` means: everything after it must be passed by name.

### `*args` and `**kwargs`
```python
def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    ...
log_event("tool_call", name="get_portfolio", ms=3)
```
- `**fields` collects all extra named arguments into a dict.
- Here `fields` becomes `{"name": "get_portfolio", "ms": 3}`.
- `*args` is the same idea for extra positional arguments (a tuple).

### Unpacking with `*` and `**`
```python
messages = [*session.messages, *new_messages]
state = {**S0, "turn": 1}
```
- `*list` spreads the items of a list.
- `**dict` spreads the keys and values of a dict.
- It builds a new list or dict. The old ones do not change.

### Returning several values
```python
async def _timed_tool_call(...) -> tuple[ToolResult, ToolCallRecord]:
    return result, record
```
- `return a, b` returns a tuple of two values.
- The caller can unpack it: `result, record = await ...`.

### Nested functions (closures)
```python
# domain/tools.py
def build_tools(repo, knowledge, guardrails):
    async def get_portfolio(ctx, args):
        return await repo.get_portfolio(ctx.customer_id)
    return [Tool("get_portfolio", ..., get_portfolio)]
```
- A function can be defined inside another function.
- The inner function can use the outer variables, like `repo`. This is a "closure".
- That is how each tool handler gets the repository without a global variable.

### Functions are values
```python
Tool("get_portfolio", "Get balance...", NoArgs, get_portfolio)
```
- You can pass a function without calling it. Leave out the `()`.
- `get_portfolio` is the function. `get_portfolio()` would run it.

### lambda
```python
ranked = sorted(zip(scores, docs), key=lambda p: p[0], reverse=True)
```
- `lambda p: p[0]` is a tiny nameless function. It returns the first item of `p`.
- `sorted` uses it to know what to sort by.

---

## 5. Classes

### What a class is
```python
class MemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def get_or_create(self, session_id: str) -> Session:
        ...
```
- A class is a blueprint. An object is one thing built from it.
- `MemorySessionStore()` makes a new object.
- Functions inside a class are called methods.

### `__init__` and `self`
```python
def __init__(self, llm, sessions):
    self._llm = llm
    self._sessions = sessions
```
- `__init__` runs when you create the object. It is the constructor.
- `self` is the object itself. Python passes it for you.
- `self._llm = llm` saves a value on the object so other methods can use it.

### Using a class
```python
agent = Agent(llm, sessions, tools, guardrails, prompt, llm_timeout_s=30)
result = await agent.run_turn("s1", "hi")
```
- Create with `ClassName(...)`. No `new` keyword.
- Call a method with `object.method(...)`.
- You do not pass `self`. It is added automatically.

### Why does `agent.py` have several classes?
```python
# core/agent.py
class ToolCallRecord(BaseModel): ...   # a record of one tool call
class TurnResult(BaseModel): ...       # what a turn returns
class _TurnStats: ...                  # a helper that collects timing during one turn
class Agent: ...                       # the logic
```
- Python has no rule of one class per file. You group things that belong together.
- Three of them are small data shapes and helpers. Only `Agent` has the logic.
- This file is about "one turn of the agent", so everything for a turn is here.

### Inheritance
```python
class FailingRepository(FakeRepository):
    async def get_portfolio(self, customer_id): raise ConnectionError("backend down")
```
- `class Child(Parent)` means the child gets everything from the parent.
- The child can replace some methods. This is called overriding.
- `FailingRepository` is a normal fake repository where reads always fail.

### Custom exceptions are classes too
```python
class ToolExecutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
```
- Inheriting from `Exception` makes your own error type.
- `super().__init__(...)` calls the parent's constructor.
- Extra data like `code` is saved on the object.

### `@property`
```python
@property
def escalated(self) -> bool:
    return self.handoff is not None
```
- It lets a method be used like an attribute: `session.escalated`, with no `()`.
- The value is calculated each time you read it.

### `@staticmethod` and `@classmethod`
```python
# adapters/postgres_repository.py
@classmethod
async def connect(cls, dsn: str) -> "PostgresRepository":
    return cls(await asyncpg.create_pool(dsn, ...))
```
- A `classmethod` gets the class (`cls`) instead of an object. Here it is a "named constructor".
- A `staticmethod` gets neither `self` nor `cls`. It is a plain function placed inside the class.
- Call a classmethod like `PostgresRepository.connect(dsn)`.

### Class attributes vs object attributes
```python
class Settings(BaseSettings):
    model: str = "claude-sonnet-5-5"
```
- In plain classes, a name set inside `__init__` with `self.` belongs to one object.
- In pydantic and dataclasses, names with types at the class level are the fields.
- Pydantic builds the constructor for you from those fields.

---

## 6. BaseModel (pydantic)

### What it is
```python
from pydantic import BaseModel

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
```
- `BaseModel` is a class from the `pydantic` library. It makes "data classes with checking".
- You list the fields with types. Pydantic writes the constructor.
- If the data is wrong, it raises an error right away.

### Creating and reading
```python
call = ToolCall(id="t1", name="get_portfolio", arguments={})
print(call.name)
```
- Always pass fields by name.
- Read a field with a dot: `call.name`.
- Missing a required field raises `ValidationError`.

### It checks and converts
```python
class WithdrawalArgs(BaseModel):
    amount_nis: float = Field(gt=0)

WithdrawalArgs(amount_nis="5000")   # works: "5000" becomes 5000.0
WithdrawalArgs(amount_nis=-1)       # error: must be greater than 0
```
- Pydantic turns compatible values into the right type.
- `Field(gt=0)` adds rules. `gt` means greater than.
- This is how we check what the AI model sends to a tool.

### Defaults
```python
class TurnResult(BaseModel):
    reply: str
    failed: bool = False
    tool_calls: list[ToolCallRecord] = []
```
- A field with `= value` is optional.
- In pydantic, `= []` is safe. Each object gets its own copy.
- In a normal class this would share one list between all objects. Do not do that outside pydantic.

### `Field(default_factory=list)`
```python
messages: list[Message] = Field(default_factory=list)
```
- It says "call `list()` to make a new empty list for each object".
- It is the same result as `= []` in pydantic. It is the style that is safe everywhere.

### Useful methods
```python
response.model_dump()          # object -> dict
response.model_dump_json()     # object -> JSON text
Model.model_validate(data)     # dict -> object (with checks)
Model.model_validate_json(txt) # JSON text -> object
Model.model_json_schema()      # the JSON schema of the model
```
- `model_json_schema()` is how our tools tell the AI model what arguments they accept.
- `model_dump(mode="json")` makes sure everything can be written as JSON.
- `model_copy(update={...})` makes a copy with some fields changed.

### Nested models
```python
class Session(BaseModel):
    messages: list[Message] = []
    pending_action: PendingAction | None = None
    handoff: Handoff | None = None
```
- A field can be another model, or a list of them.
- Pydantic checks all levels.
- `PendingAction | None` means "either a PendingAction or nothing".

### BaseSettings
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    anthropic_api_key: SecretStr
    llm_cache: bool = False
```
- It is a `BaseModel` that fills its fields from environment variables and the `.env` file.
- `ANTHROPIC_API_KEY` in `.env` fills `anthropic_api_key`. Names are not case sensitive.
- `SecretStr` hides the value when printed. Use `.get_secret_value()` to read it.

---

## 7. Protocol, dataclass and other class helpers

### Protocol (an interface)
```python
# core/interfaces.py
class LLMProvider(Protocol):
    async def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...
```
- A `Protocol` lists the methods a class must have. It has no code.
- Any class with a matching `complete` method fits it. It does not need to inherit from it.
- This is called "structural typing" or "duck typing". Real and fake LLMs both fit.

### The three dots `...`
```python
async def save(self, session: Session) -> None: ...
```
- `...` is a valid "empty body" in Python. It means "nothing here".
- You use it when a method is only a signature.

### dataclass
```python
# core/tools.py
@dataclass
class ToolContext:
    session: Session
    idempotency_key: str | None = None
```
- `@dataclass` writes `__init__` for you from the listed fields.
- It is a lighter cousin of `BaseModel`. It does not check or convert values.
- `@dataclass(frozen=True)` makes the object read-only after it is created. `Tool` uses that.

### BaseModel or dataclass?
- Use `BaseModel` when data comes from outside (API, AI model, JSON) and must be checked.
- Use `@dataclass` for small internal containers like `Container` and `Tool`.
- Both give you a constructor with named fields.

### `Enum`-like things
We do not use `Enum`. We use `Literal[...]` and plain strings like `"read"` and `"write"`.
- It is simpler.
- The downside: a typo is only caught by the editor, not by Python.

---

## 8. Decorators (the `@` lines)

### What a decorator is
```python
@property
def escalated(self): ...
```
- A decorator is a function that wraps another function or class.
- You write `@name` on the line above.
- It changes how the thing below behaves.

### The ones in this project
```python
@dataclass                      # builds __init__ for the class
@property                       # method used like an attribute
@classmethod                    # method that receives the class
@staticmethod                   # plain function inside a class
@asynccontextmanager            # turns a generator into an "async with" helper
@app.get("/health")             # registers a web route in FastAPI
@pytest.fixture                 # marks a test helper
@pytest.mark.parametrize(...)   # runs a test many times with different values
```

### FastAPI routes
```python
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    ...
```
- `@app.post("/chat")` says: "when a POST arrives at /chat, call this function".
- FastAPI reads the type `ChatRequest` and builds it from the JSON body.
- If the body is wrong, FastAPI answers 422 on its own.

---

## 9. async and await

### Why async
- Our program mostly waits: for the AI model, for the database.
- With `async`, while one request waits, Python can work on another one.
- It uses one thread. It does not run code at the same time. It switches while waiting.

### async def and await
```python
async def run_turn(self, session_id: str, user_text: str) -> TurnResult:
    session = await self._sessions.get_or_create(session_id)
```
- `async def` makes a "coroutine function". Calling it does not run it yet.
- `await` runs it and waits for the result. Other tasks can run meanwhile.
- You can only use `await` inside an `async def`.

### Forgetting await
```python
result = self._sessions.get_or_create(session_id)        # wrong: this is a coroutine object
result = await self._sessions.get_or_create(session_id)  # right
```
- Without `await` you get a coroutine object and a warning, not the value.
- This is the most common async mistake.

### asyncio.run
```python
if __name__ == "__main__":
    asyncio.run(main())
```
- This starts the "event loop" and runs `main()` until it is done.
- The event loop is the thing that switches between waiting tasks.
- You call it once, at the top of a program. FastAPI and pytest do it for us.

### asyncio.gather (run at the same time)
```python
timed = await asyncio.gather(*(self._timed_tool_call(c, session) for c in calls))
```
- It starts all the coroutines together and waits until all are done.
- Results come back in the same order as the inputs.
- If the AI model asks for two tools, they run in parallel. A test checks this.

### asyncio.timeout
```python
async with asyncio.timeout(self._llm_timeout_s):
    return await self._llm.complete(...)
```
- If the block takes longer than the time, Python raises `TimeoutError`.
- We catch it and retry once.
- While you sit on a breakpoint, time still passes. That is why debug configs set long timeouts.

### asyncio.sleep
```python
await asyncio.sleep(self._retry_backoff_s * 2**attempt)
```
- It waits without blocking other tasks. Never use `time.sleep` in async code.
- `2**attempt` is 2 to the power of attempt: 1, 2, 4... This is "exponential backoff".

### async with
```python
async with self._pool.acquire() as conn, conn.transaction():
    ...
```
- Like `with`, but the setup and cleanup can `await`.
- It always cleans up, even after an error.
- You can put two on one line, separated by a comma.

### asyncio.to_thread
```python
user_text = (await asyncio.to_thread(input, "you> ")).strip()
```
- `input()` blocks. It would freeze the event loop.
- `to_thread` runs it in another thread and lets us `await` it.

### yield in async code
```python
@asynccontextmanager
async def lifespan(app):
    app.state.container = await build_container(settings)   # runs at startup
    try:
        yield                                               # the app runs here
    finally:
        await app.state.container.close()                   # runs at shutdown
```
- `yield` pauses the function. Code before it is setup, code after it is cleanup.
- FastAPI runs the "before" part at start, and the "after" part when the server stops.
- Pytest fixtures use the same trick.

---

## 10. Errors and exceptions

### try / except
```python
try:
    reply = await self._loop(session, new_messages, stats)
except LLMError:
    reply = None
```
- The code in `try` runs. If it raises an error, Python jumps to a matching `except`.
- If no error happens, `except` is skipped.
- Catch only the errors you can handle.

### Several errors, and `as`
```python
except (TimeoutError, LLMError) as exc:
    log_event("llm_retry", exc_info=True)
```
- A tuple in `except` catches any of them.
- `as exc` gives you the error object.
- `exc_info=True` makes the logger print the full traceback.

### raise
```python
raise ToolExecutionError("not_found", "No matching withdrawal request.")
```
- `raise` throws an error on purpose.
- Everything stops until some `except` catches it.
- A bare `raise` inside `except` throws the same error again.

### raise ... from ...
```python
raise LLMError(f"LLM failed: {exc!r}") from exc
```
- It links the new error to the original one.
- The traceback shows both: "the above error caused the following error".
- It keeps the real cause visible.

### finally
```python
try:
    response = await self._call_llm(history)
finally:
    stats.llm_ms += _ms_since(started)
```
- `finally` always runs, with or without an error.
- We use it to record the time even when the call fails.

### except Exception
```python
except Exception:  # noqa: BLE001
    error_code = "internal_error"
```
- `Exception` catches almost every error. It is very broad.
- We use it on purpose in the tool registry. One broken tool must not crash the whole loop.
- Normally, catching this wide is a bad habit. That is why the comment explains it.

### Which line runs?
```python
for attempt in range(2):
    try:
        return await tool.handler(ctx, args)
    except Exception:
        if attempt == 1:
            raise
        await asyncio.sleep(0.2)
```
- First failure: wait, then loop again.
- Second failure: `raise` sends the error up.
- Success at any time: `return` leaves the function.

---

## 11. Collections and loops

### list, tuple, dict, set
```python
items = [1, 2, 3]          # list: ordered, can change
pair = ("a", 1)            # tuple: ordered, cannot change
data = {"name": "x"}       # dict: key -> value
seen = {1, 2, 3}           # set: unique values
```
- Read a list item with `items[0]`. The last item is `items[-1]`.
- Read a dict value with `data["name"]`, or `data.get("name")` which gives `None` if missing.
- `x in data` checks keys. `x in items` checks values.

### Slices
```python
ranked[:k]        # the first k items
text[:80]         # the first 80 characters
```
- `a[start:end]` takes a part. `end` is not included.
- `[:k]` means "from the start up to k".

### for loops
```python
for h in self._holdings:
    ...
for key, value in data.items():
    ...
for attempt in range(2):
    ...
```
- `for x in something` goes through the items.
- `.items()` gives key and value together.
- `range(2)` gives 0 and 1.

### Unpacking in a loop
```python
for score, (doc_id, title, text) in ranked[:k]:
    ...
```
- Each item is a pair. The second part is itself a tuple.
- Python splits both levels into names in one line.

### List comprehension
```python
holdings = [
    {"product": self._products[h["product_id"]]["name"], "value_nis": h["value_nis"]}
    for h in self._holdings
    if h["customer_id"] == customer_id
]
```
- Format: `[what_to_make for item in things if condition]`.
- It builds a new list in one expression.
- Read it as: "for each h that matches, make this dict".

### Dict comprehension
```python
self._tools = {tool.name: tool for tool in tools}
```
- Same idea, with `{key: value for ...}`.
- Here: a dict from tool name to the tool.

### Generator expression
```python
sum(h["value_nis"] for h in holdings)
sum(t.is_error for t in result.tool_calls)
```
- Like a list comprehension, but with no brackets, and it makes items one by one.
- `sum(True/False values)` counts the True ones.

### Useful built-ins
```python
any(...)  all(...)  len(x)  sorted(x)  zip(a, b)  enumerate(x)  sum(x)  isinstance(x, T)
```
- `zip(a, b)` walks two lists together. `strict=True` fails if the lengths differ.
- `isinstance(item, Exception)` checks the type.
- `"".join(parts)` glues a list of strings together.

### Strings
```python
text.lower()   text.strip()   text.split(",")   "-".join(parts)   text.startswith("a")
```
- Strings cannot change. These methods return a new string.
- Use single or double quotes. They are the same.
- Triple quotes allow many lines.

---

## 12. Other things you will meet

### Context managers (`with`)
```python
with open(path) as f:
    data = f.read()
```
- `with` sets something up, and cleans up at the end, even after an error.
- Files, locks and database connections use it.

### ContextVar
```python
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
correlation_id.set("abc")
correlation_id.get()
```
- It is a variable whose value is separate for each request (each async task).
- We use it so every log line can show the request id, without passing it around.
- Like a thread-local variable, but for async code.

### `json` and `yaml`
```python
json.dumps(payload, default=str)   # Python object -> JSON text
json.loads(text)                   # JSON text -> Python object
yaml.safe_load(text)               # YAML text -> dict
```
- `default=str` tells `dumps` to use `str()` for things it cannot write, like dates.
- `safe_load` is the safe way to read YAML.

### Environment and files
```python
path.read_text(encoding="utf-8")
path.exists()
os.replace(tmp, path)
```
- `Path` objects have handy methods.
- `os.replace` swaps a file in one step. We write to a temp file first so we never leave half a file.

### `hashlib`
```python
hashlib.sha256(encoded).hexdigest()
```
- It makes a fixed-length "fingerprint" of data.
- Same input gives the same result. We use it as the key of the dev cache.

### `uuid`
```python
str(uuid.uuid4())
```
- It makes a random unique id.
- We use it for session ids and idempotency keys.

### `time.perf_counter()`
- It gives a very precise clock, good for measuring how long something took.
- Take it twice and subtract.
- Do not use it as a calendar time.

### The `Any` escape hatch
- `Any` turns off type checking for that value.
- It is why Ctrl+click did not work on `app.state.container`.

### Naming style
- `snake_case` for functions and variables.
- `PascalCase` for classes.
- `UPPER_CASE` for constants.

---

## 13. Tests (pytest)

### A test is a function
```python
def test_p95_and_report():
    assert p95([100.0] * 19 + [900.0]) == 100.0
```
- Name starts with `test_`. Files start with `test_`.
- `assert` fails the test if the condition is False.
- No class is needed.

### async tests
```python
async def test_returns_llm_text_and_token_counts(rig):
    result = await r.agent.run_turn("s1", "hi")
```
- Our `pyproject.toml` sets `asyncio_mode = "auto"`, so `async def test_...` just works.
- `await` is allowed inside.

### Fixtures (the argument names)
```python
@pytest.fixture
def rig():
    def make(script, **kwargs) -> Rig:
        return Rig(script, **kwargs)
    return make

async def test_x(rig):      # pytest passes the fixture in by name
    r = rig([say("hello")])
```
- A fixture is a helper that pytest builds for a test.
- A test asks for it by putting the same name as an argument.
- Fixtures live in `tests/conftest.py` so every test file can use them.

### parametrize
```python
@pytest.mark.parametrize("retries,expected_calls", [(0, 1), (2, 3)])
async def test_retry_count_is_configurable(rig, retries, expected_calls): ...
```
- It runs the same test once for each pair of values.
- Each run shows as its own test.

### Built-in fixtures we use
- `tmp_path`: a fresh temporary folder for the test.
- `caplog`: collects log lines, so you can check them.
- `pytest.raises(SomeError)`: passes only if that error is raised inside the block.

### Fake objects
- `FakeLLMProvider` returns scripted answers. No network, no cost.
- Because `core` only knows the `Protocol`, a fake can replace the real thing.
- This is why tests run in seconds.

---

## 14. Tools and project files

### Virtual environment (`.venv`)
- A folder with its own Python and its own installed packages.
- It keeps this project separate from others.
- VS Code must use `.venv\Scripts\python.exe`, or imports will fail.

### pip and `pyproject.toml`
- `pip install -e ".[dev]"` installs the project's packages, and the dev extras (pytest, ruff).
- `pyproject.toml` lists dependencies and tool settings.
- `-e` means "editable": code changes apply without reinstalling.

### ruff
- `ruff check .` finds problems. `ruff format .` fixes the layout.
- It enforces line length 100 and sorted imports.
- A `# noqa` comment turns a rule off for one line.

### `.env`
- A text file with `NAME=value` lines. Never commit it.
- `pydantic-settings` reads it into `Settings`.
- `.env.example` is the safe template that is committed.

### Docker files
- `Dockerfile` says how to build the API image.
- `docker-compose.yml` starts Postgres and the API together.
- `.dockerignore` lists files that are not copied into the image.

---

## 15. How to read an error message

### Traceback
```text
Traceback (most recent call last):
  File "core/tools.py", line 143, in _invoke
    return await tool.handler(ctx, args)
  File "adapters/fake_repository.py", line 84, in get_portfolio
    raise ConnectionError("backend down")
ConnectionError: backend down
```
- Read from the bottom up. The last line is the actual error.
- The line above it is where it happened. Lines higher up are who called it.
- "most recent call last" means the newest call is at the bottom.

### Common errors
- `NameError`: you used a name that does not exist. Check spelling and imports.
- `AttributeError`: the object has no such attribute. Often it is `None`.
- `ValidationError`: pydantic rejected the data. Read which field and why.
- `ModuleNotFoundError`: wrong interpreter, or wrong folder. Check `.venv`.

### Debug tips
- Put a breakpoint, then press F11 to step into a function and F10 to step over it.
- Add a variable to the Watch panel to see it change.
- Read the log lines. The `file:line function` part tells you where each one came from.

---

## 16. Worked example: MemorySessionStore and interfaces

This part takes one small class and explains everything about it. File: `adapters/memory_session_store.py`.

### What it is for
- A chat has many messages. The AI model does not remember them, so we must save them between messages.
- The "session" holds the messages, the verified customer, and other state.
- `MemorySessionStore` keeps all sessions in a Python dictionary, in memory.

### The whole class
```python
# adapters/memory_session_store.py
from core.session import Session


class MemorySessionStore:
    """Per-process dict. Replace with Redis (same interface) to run more than one replica."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def get_or_create(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            session = Session(id=session_id)
            self._sessions[session_id] = session
        return session

    async def save(self, session: Session) -> None:
        self._sessions[session.id] = session
```
- It is only 15 lines.
- It has one piece of data (`_sessions`) and two methods.
- The next cards go through it line by line.

### Line by line: the data
```python
def __init__(self) -> None:
    self._sessions: dict[str, Session] = {}
```
- `__init__` runs once, when the store is created.
- `self._sessions` is an empty dictionary. Keys are session ids (text). Values are `Session` objects.
- The `_` at the start says "private, do not use from outside".

### Line by line: get_or_create
```python
async def get_or_create(self, session_id: str) -> Session:
    session = self._sessions.get(session_id)
    if session is None:
        session = Session(id=session_id)
        self._sessions[session_id] = session
    return session
```
- `.get(session_id)` looks in the dictionary. It gives `None` if the id is not there.
- If it is missing, we create a new empty `Session` and store it.
- Either way we return a session. The caller never needs to check.

### Line by line: save
```python
async def save(self, session: Session) -> None:
    self._sessions[session.id] = session
```
- It puts the session into the dictionary under its own id.
- If the id already exists, the old value is replaced.
- `-> None` means it returns nothing.

### Why are these methods `async` if they never `await`?
- Nothing inside them waits. Dictionary access is instant.
- They are `async` because the interface says so. The caller always writes `await store.get_or_create(...)`.
- A Redis version would really wait for the network, so it needs `async`. The caller code stays the same.

### What is the "interface"?
```python
# core/interfaces.py
class SessionStore(Protocol):
    async def get_or_create(self, session_id: str) -> Session: ...

    async def save(self, session: Session) -> None: ...
```
- It is a list of two method signatures. There is no code inside (`...` means empty).
- It says: "anything that can do these two things is a session store".
- It is the contract. The agent only knows this contract.

### How does MemorySessionStore implement it?
Look at the class line again:
```python
class MemorySessionStore:       # no "(SessionStore)", no "implements"
```
- There is no `implements` and no inheritance. It simply has the same two methods with the same names and types.
- This is "duck typing": if it walks like a duck and quacks like a duck, it is a duck.
- The editor (Pylance) checks the match for you. Python itself does not check at runtime.

### Where the match is used
```python
# core/agent.py
def __init__(self, llm: LLMProvider, sessions: SessionStore, ...):
    self._sessions = sessions
```
- The `Agent` asks for a `SessionStore`. It does not name `MemorySessionStore`.
- In `app/container.py` we write `sessions = MemorySessionStore()` and pass it in.
- If the methods did not match, the editor would show a red line there.

### Why we need an interface here
Three real reasons in this project:
- **Production needs something else.** Memory is lost when the server restarts. Two servers cannot share it. A real system would use Redis.
- **Tests stay simple.** The agent can be tested without any real storage or network.
- **The core must stay clean.** `core/` is not allowed to import from `adapters/`. The interface lets the core use storage without knowing which one.

### What swapping would look like (not built yet)
```python
class RedisSessionStore:
    def __init__(self, redis) -> None:
        self._redis = redis

    async def get_or_create(self, session_id: str) -> Session:
        raw = await self._redis.get(f"session:{session_id}")
        return Session.model_validate_json(raw) if raw else Session(id=session_id)

    async def save(self, session: Session) -> None:
        await self._redis.set(f"session:{session.id}", session.model_dump_json(), ex=3600)
```
- Same two methods, same signatures. That is the whole job.
- Then change one line in `app/container.py`. Nothing in `core/` changes.
- This sketch is an idea. It is not in the project.

### A hidden difference: shared object vs copy
- `MemorySessionStore` gives back the same object every time. If you change it, the stored one changes too.
- Redis would give back a fresh copy each time. A change is lost unless you call `save`.
- That is why the agent always calls `save(...)` at the end of a turn. It works with both kinds.

### Dependency injection, again
- The agent receives its store from outside, in `__init__`. That is dependency injection.
- The interface says what it needs. `container.py` decides what it gets.
- Tests pass something else. The agent code does not change.

### Quick check: can you answer these?
- Why is there no `implements` keyword?
- What would you change to use Redis?
- Why does the agent call `save` even though the memory version does not need it?

---

## 17. Worked example: container.py (the builder)

File: `app/container.py`. This file answers one question: "who creates all the objects and connects them?"

### What the file is for
- The agent needs an LLM, a session store, tools and guardrails. Someone must create them.
- `container.py` is that someone. It creates every piece and plugs them together.
- Its docstring calls it the "composition root": the one place that knows which real class is used for each interface.

### What is inside it
```python
@dataclass
class Container:                 # a small box that holds the results
    agent: Agent
    sessions: SessionStore
    close: Callable[[], Awaitable[None]]

async def build_container(...)   # the function that does the real work
async def build_repository(...)  # helper: picks Postgres or the fake data
async def _noop()                # helper: a "do nothing" function
```
- `Container` is only a box with three things inside.
- The builder is the function `build_container`. The class itself builds nothing.
- The two helpers are small parts of that job.

### When is it used?
```python
# api/main.py (when the server starts)
app.state.container = await build_container(settings)

# cli.py (when the chat program starts)
container = await build_container(Settings())

# evals/runner.py (once for every eval case)
container = await build_container(settings, llm=llm, repository=repo)
```
- It runs once at startup. It does not run on every chat message.
- After that, every request reuses the same agent.
- Tests do not use it. They build their own small version in `tests/conftest.py`.

### Built once, reused for every request
```python
# api/main.py
@asynccontextmanager
async def lifespan(app):
    app.state.container = await build_container(settings)   # once, at startup
    try:
        yield                                               # the server runs here
    finally:
        await app.state.container.close()                   # once, at shutdown

@app.post("/chat")
async def chat(request):
    result = await app.state.container.agent.run_turn(...)  # every request, same agent
```
- At startup the container is built and saved in `app.state.container`.
- Every request after that uses the same agent. Nothing is rebuilt per message.
- At shutdown, `close()` runs once to close the database pool.

### What "built once" means for you
- **Changes need a restart.** The code, the system prompt, `domain/config.yaml` and `.env` are read at startup. A running server does not see your edits. Restart it, or press F5 again in VS Code.
- **State is shared.** All requests use the same session store and the same database pool. That is why a chat continues between messages.
- **A restart clears memory.** `MemorySessionStore` lives inside the process, so a restart deletes all chats. The dev cache folder and the database stay.

### Is it the main builder of the agent?
```python
# app/container.py
agent = Agent(llm, sessions, tools, guardrails, system_prompt, ...)
```
- Yes. This is the only place in the app that calls `Agent(...)`.
- The API and the CLI never create an agent themselves. They ask the container.
- So if you want to know "what is the agent made of?", read this one function.

### build_container, step by step
```python
repository, close = await build_repository(settings)       # 1. database (or fake data)
llm = AnthropicLLM(api_key, settings.model)                # 2. the AI model client
guardrails = Guardrails(GuardrailConfig(**config["guardrails"]))   # 3. policy rules
tools = ToolRegistry(build_tools(repository, BM25Index(...), guardrails), ...)  # 4. tools
sessions = MemorySessionStore()                            # 5. where chats are saved
agent = Agent(llm, sessions, tools, guardrails, prompt)    # 6. the agent itself
return Container(agent=agent, sessions=sessions, close=close)   # 7. put it in a box
```
- Each step creates one piece.
- The agent comes last because it needs all the other pieces.
- The order matters: the tools need the repository, so the repository comes first.

### Step 1 in detail: choosing the data source
```python
async def build_repository(settings):
    if settings.data_backend == "fake":
        return FakeRepository(DATA_DIR / "seed.json"), _noop
    repo = await PostgresRepository.connect(settings.database_url)
    await repo.init_schema_and_seed(...)
    return repo, repo.close
```
- The setting `DATA_BACKEND` in `.env` decides: fake data or Postgres.
- For Postgres it connects, creates the tables and loads the sample data.
- It returns two things: the repository, and a function to close it later.

### Why does Container hold `close`?
- The Postgres connection pool must be closed when the server stops.
- `api/main.py` calls `await container.close()` at shutdown.
- For fake data there is nothing to close, so `_noop` (do nothing) is used. The caller does not need an `if`.

### Choosing real pieces with settings
```python
llm = AnthropicLLM(...)
if settings.llm_cache:
    llm = CachingLLMProvider(llm, LLM_CACHE_DIR, settings.model)
```
- A setting turns a feature on or off. Here: the development cache.
- `CachingLLMProvider` wraps the real LLM. It has the same methods, so the agent cannot tell the difference.
- This is how wiring decisions live in one place.

### Why `llm` and `repository` are parameters
```python
async def build_container(settings, *, llm=None, repository=None):
    if repository is None:
        repository, close = await build_repository(settings)
    if llm is None:
        llm = AnthropicLLM(...)
```
- Callers may pass their own. If they do not, the container builds the normal one.
- The eval runner passes its own `llm` so the dev cache can never be used there.
- `None` means "not given, use the default".

### Why we need such a file
Imagine we did not have it.
- **Inside the Agent:** the agent would create `AnthropicLLM` itself. It would be stuck with it, and tests would call the real API.
- **Everywhere:** the API, the CLI and the evals would each repeat the same 30 lines. They would slowly drift apart.
- **With the container:** the agent only receives things. The wiring is in one file you can read in two minutes.

### How it connects to dependency injection
- Dependency injection means "give the object what it needs from outside".
- The container is the thing that does the giving.
- `Agent.__init__` is the receiving side. `build_container` is the giving side.

### What changes when something changes
- **Use Redis for sessions:** change `sessions = MemorySessionStore()` to a Redis store. Nothing in `core/` changes.
- **Use another LLM:** change the line that creates `AnthropicLLM`.
- **New domain:** `build_tools`, the prompt and the config come from `domain/`. This file barely changes.

### Do real codebases look like this?
Partly. The idea is common. The exact shape is more strict than usual.
- Dependency injection and one place that wires everything are standard in backend code.
- The same job has other names: `main.py`, `app.py`, `bootstrap.py`, FastAPI `Depends(...)` functions, or a DI library.
- A file named `container.py` is possible, but not guaranteed. Look for where the app starts and where the database and clients are created.

### What is different in this project
- **Very clean interfaces.** Here `core/` never imports adapters. Real teams are usually looser, with fewer interfaces and more direct imports.
- **A hand-written agent loop.** I wrote it so I can explain every line. Many teams use a framework instead: LangGraph, OpenAI Agents SDK, Pydantic AI, LlamaIndex or Claude Agent SDK. Others have an internal platform where the loop already exists.
- Teams that need tight control of safety, latency and testing often write their own. Both ways exist.

### What to do in a new job
- Find the entry point and read how the app is wired. That is the equivalent of `container.py`.
- Learn what is configurable (prompts, tools, integrations, evals) and what is platform code.
- The skill that transfers is the boundaries: what is gated in code, how state is stored, how it is tested. File names matter less.
- You can say in an interview: "I wrote the loop by hand to understand it and control the guardrails. In a real team I would use their framework with the same boundaries."

### Quick check: can you answer these?
- Why is the agent created last?
- Who calls `build_container`, and how often?
- Why does the container return a `close` function?

---

## 18. Worked example: agent.py (the brain)

File: `core/agent.py`. This is the heart of the project. It runs one turn of a conversation.

### What the file is for
- A "turn" is: the customer sends one message, and the agent sends one reply.
- To make that reply, the agent may ask the AI model several times and run several tools.
- `agent.py` controls that whole process. It is called "the agent loop".

### What is inside it
```python
FALLBACK_REPLY = "I'm having trouble right now..."   # a constant

class ToolCallRecord(BaseModel): ...    # data: one tool call, for reports
class TurnResult(BaseModel): ...        # data: what a turn returns
class _TurnStats: ...                   # helper: collects timings during a turn
class Agent: ...                        # the logic

def _ms_since(started): ...             # tiny helper function at the bottom
```
- Three small classes hold data. One class, `Agent`, holds the logic.
- They live together because they all belong to "one turn".
- Names that start with `_` are private to this file.

### FALLBACK_REPLY
```python
FALLBACK_REPLY = "I'm having trouble right now. Please try again in a moment."
```
- It is a constant. The name is in capitals by habit.
- It is the safe message used when the AI model cannot be reached.
- Tests import it, so the text is written only once.

### The data classes
```python
class TurnResult(BaseModel):
    reply: str
    failed: bool = False
    escalated: bool = False
    tool_calls: list[ToolCallRecord] = []
    latency_ms: float = 0
```
- `TurnResult` is what `run_turn` gives back. The API uses it to build its answer.
- `ToolCallRecord` is one entry in `tool_calls`: name, arguments, result, time.
- They are `BaseModel`, so the fields are typed and checked. See section 6.

### Why `_TurnStats` is a plain class
```python
class _TurnStats:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.llm_ms = 0.0
        self.tools_ms = 0.0
        self.tool_calls: list[ToolCallRecord] = []
```
- It is a notepad for one turn. The code adds to its numbers again and again.
- It is not data from outside, so it needs no checking. A plain class is enough.
- At the end its numbers are copied into a `TurnResult`.

### The Agent receives its tools
```python
class Agent:
    def __init__(self, llm, sessions, tools, guardrails, system_prompt, *, llm_timeout_s, ...):
        self._llm = llm
        self._sessions = sessions
        ...
```
- This is dependency injection. See sections 16 and 17.
- The agent stores each piece on `self` so every method can use it.
- The agent never creates an LLM or a database. It only uses what it was given.

### Which methods are public?
```python
async def run_turn(...)        # public: others call this
async def _loop(...)           # private: only used inside Agent
async def _call_llm(...)       # private
async def _run_tools(...)      # private
def _finish(...)               # private
```
- Only `run_turn` is called from outside (by the API, CLI and evals).
- The others start with `_`. They are the steps inside it.
- This keeps `run_turn` short: it reads like a list of steps.

### run_turn, step by step
```python
async def run_turn(self, session_id: str, user_text: str) -> TurnResult:
    stats = _TurnStats()                                    # 1. start the notepad
    session_id_var.set(session_id)                          # 2. tag the log lines
    session = await self._sessions.get_or_create(session_id)  # 3. load the chat
    if session.escalated:                                   # 4. already handed to a human?
        return self._finish(session, stats, ...)
    session.turn += 1                                       # 5. count this turn
    new_messages = [Message(role="user", content=user_text)]  # 6. start this turn's messages
    ...
```
- Steps 1 to 6 are preparation.
- Then the loop runs (`_loop`), then the checks, then the save.
- The next cards explain each part.

### The escalated shortcut
```python
if session.escalated:
    return self._finish(session, stats, self._guardrails.config.escalated_reply)
```
- If a human already took over, we do not ask the AI model anymore.
- We just return the fixed "a human agent will continue" message.
- It is fast and costs nothing.

### Why `new_messages` is a separate list
```python
new_messages = [Message(role="user", content=user_text)]
```
- We collect this turn's messages here, not directly in the session.
- They are added to the session only at the end, when everything worked.
- If the turn fails halfway, the session stays clean.

### try / except around the loop
```python
try:
    reply = await self._loop(session, new_messages, stats)
except LLMError:
    reply = None
```
- `_loop` raises `LLMError` when the AI model failed twice.
- We catch it and set `reply = None`. This is the "something went wrong" signal.
- `_loop` also returns `None` when it hit the maximum number of steps.

### The failure branch
```python
if reply is None:
    await self._sessions.save(session)
    return self._finish(session, stats, FALLBACK_REPLY, failed=True)
```
- We still save the session. State like "customer is verified" must not be lost.
- We do not save the half-finished messages. A tool call without its result breaks the next AI request.
- The customer sees the fallback message, and `failed=True` is recorded.

### The output guardrail
```python
violation = False
try:
    self._guardrails.check_output(reply)
except PolicyViolation as exc:
    log_event("policy_violation", detail=str(exc))
    reply, violation = self._guardrails.config.advice_refusal_message, True
```
- `check_output` raises `PolicyViolation` if the reply looks like investment advice.
- Then we replace the reply with the refusal message. The bad text is never saved.
- `reply, violation = a, b` sets two variables in one line (a tuple).

### Saving the turn
```python
new_messages.append(Message(role="assistant", content=reply))
session.messages = [*session.messages, *new_messages]
await self._sessions.save(session)
```
- The final reply is added as the last message.
- `[*a, *b]` builds a new list with the items of `a`, then of `b`.
- Then the session is saved. Now the next message can see the whole history.

### The loop (_loop)
```python
for _ in range(self._max_iterations):
    history = [*session.messages, *new_messages]
    response = await self._timed_llm_call(history, stats)
    if not response.tool_calls:
        return response.text
    new_messages.append(Message(role="assistant", content=response.text, tool_calls=response.tool_calls))
    results = await self._run_tools(response.tool_calls, session, stats)
    new_messages.append(Message(role="user", tool_results=results))
log_event("max_iterations_reached", ...)
return None
```
- Ask the AI model. If it answers with text, we are done: `return response.text`.
- If it asks for tools, run them, add the results to the messages, and ask again.
- At most 6 rounds. After that we give up and return `None`.

### What the loop does in a real example
Customer: "What's my balance?" (already verified)
- Round 1: the model asks for the tool `get_portfolio`. We run it.
- Round 2: we send the result back. The model writes "Your balance is 125,400 NIS".
- No tool calls this time, so the loop returns that text.

### _timed_llm_call and finally
```python
started = time.perf_counter()
try:
    response = await self._call_llm(history)
finally:
    stats.llm_ms += _ms_since(started)
```
- It measures how long the AI call took and adds it to the notepad.
- `finally` runs even if the call fails, so the time is always counted.
- `+=` adds to the existing value. One turn can have several AI calls.

### The retry loop (_call_llm)
```python
for attempt in range(self._llm_retries + 1):
    try:
        async with asyncio.timeout(self._llm_timeout_s):
            return await self._llm.complete(self._system_prompt, history, self._tools.specs())
    except (TimeoutError, LLMError) as exc:
        if attempt == self._llm_retries:
            raise LLMError(f"LLM failed after {attempt + 1} attempts: {exc!r}") from exc
        await asyncio.sleep(self._retry_backoff_s * 2**attempt)
```
- With 1 retry the loop runs twice (`range(2)` gives 0 and 1).
- Attempt 0 fails: wait 0.5 seconds, try again. Attempt 1 fails: raise the error.
- `asyncio.timeout(30)` stops an attempt that takes longer than 30 seconds.

### The odd last line
```python
raise AssertionError("unreachable")
```
- The loop always returns or raises before it ends. This line should never run.
- It is there so the type checker knows the function never returns `None` by accident.
- If it ever runs, there is a bug, and it fails loudly.

### Running tools at the same time
```python
timed = await asyncio.gather(*(self._timed_tool_call(c, session) for c in calls))
stats.tool_calls.extend(record for _, record in timed)
return [result for result, _ in timed]
```
- If the model asks for 2 tools, both start together. `gather` waits for both.
- Each item in `timed` is a pair `(result, record)`. We split the pairs in two ways.
- `for _, record in timed` ignores the result and keeps the record.

### _timed_tool_call
```python
result = await self._tools.execute(call, session)
record = ToolCallRecord(name=call.name, ..., ms=_ms_since(started))
return result, record
```
- It runs one tool through the registry. All the safety gates are inside `execute`.
- It builds a record with the time taken.
- It returns two things as a tuple.

### _finish: one exit for the reports
```python
def _finish(self, session, stats, reply, *, failed=False, policy_violation=False) -> TurnResult:
    result = TurnResult(reply=reply, ...)
    log_event("turn", ...)
    return result
```
- Every path out of `run_turn` ends here. Even the early escalated return.
- It builds the `TurnResult` and writes the one summary log line.
- So the log has the same fields in every case.

### The helper at the bottom
```python
def _ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000
```
- It is a normal function, outside the class.
- It turns "seconds since started" into milliseconds.
- It is defined after `Agent`, which is fine. Python only looks it up when it is called.

### What the Agent does NOT know
- It does not know about Anthropic, Postgres, HTTP or files.
- It only talks to the interfaces: `LLMProvider`, `SessionStore`, the tools and the guardrails.
- That is why it can be tested with fakes, and why `core/` can be reused for a new domain.

### Quick check: can you answer these?
- Why is `new_messages` a separate list?
- What happens after two failed AI calls?
- Why is `reply is None` used as a signal?
- What does `asyncio.gather` do here?

---

## 19. Worked example: tools

Files: `domain/tools.py` (the tools themselves) and `core/tools.py` (the machinery that runs them).

### What a tool is
- A tool is a function the AI model can ask our code to run.
- The model only sees the name, a description and the arguments. It never runs anything itself.
- Our code receives the request, checks it, runs the function, and sends the result back.

### Our 7 tools
| Tool | What it does | Uses the database? |
|---|---|---|
| `verify_identity` | Checks customer ID and last 4 phone digits | yes |
| `get_portfolio` | Holdings and total balance | yes |
| `get_recent_transactions` | Latest transactions | yes |
| `get_withdrawal_status` | Status of withdrawal requests | yes |
| `request_withdrawal` | Opens a withdrawal (two steps) | yes, a write |
| `search_knowledge` | Searches fees, rules and policy documents | no, it uses the BM25 index |
| `escalate_to_human` | Hands the chat to a person | no, it only changes the session |

### Is the database a tool?
- No. The database is not a tool. Some tools use it.
- The chain is: model, then tool, then repository, then database.
- The model cannot write SQL. It can only pick from these 7 tools.

### Two files, two jobs
- `domain/tools.py` says WHAT the tools are. It is replaced when the domain changes.
- `core/tools.py` says HOW tools are run: checks, safety gates, timeouts. It never changes with the domain.
- This is the same split as everywhere else: `domain/` is swappable, `core/` is generic.

### The Tool class
```python
# core/tools.py
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    access: Literal["read", "write"] = "read"
    requires_verification: bool = True
```
- A tool is just a small record: a name, a description, the shape of its arguments, and the function to run.
- `handler` is the function. `input_model` is the class that describes the arguments.
- `access` and `requires_verification` have defaults. Most tools are "read" and need a verified customer.

### The argument classes
```python
# domain/tools.py
class WithdrawalArgs(BaseModel):
    amount_nis: float = Field(gt=0, description="Amount to withdraw in NIS")
```
- Each tool has a `BaseModel` that describes its arguments. See section 6.
- `gt=0` means the amount must be greater than zero.
- The `description` text is shown to the AI model, so it should be clear.

### What the model actually sees
```python
WithdrawalArgs.model_json_schema()
# {"properties": {"amount_nis": {"description": "Amount to withdraw in NIS",
#                                "exclusiveMinimum": 0, "type": "number"}},
#  "required": ["amount_nis"], "type": "object"}
```
- Pydantic turns the class into a JSON schema automatically.
- `Tool.spec()` sends this schema, plus the name and description, to the model.
- So the Python class is the single source of truth. We never write the schema by hand.

### A tool with no arguments
```python
class NoArgs(BaseModel):
    pass
```
- `get_portfolio` needs nothing from the model. The customer comes from the session.
- `pass` means "empty body". The class has no fields.
- Fewer arguments means fewer ways for the model to be wrong or be tricked.

### build_tools: why functions inside a function
```python
def build_tools(repo: AccountRepository, knowledge: KnowledgeIndex, guardrails: Guardrails) -> list[Tool]:
    async def get_portfolio(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
        return await repo.get_portfolio(ctx.customer_id)
    ...
    return [Tool("get_portfolio", "Get the verified customer's holdings...", NoArgs, get_portfolio), ...]
```
- The handlers are defined inside `build_tools`. They can use `repo`, `knowledge` and `guardrails` directly. This is a closure.
- That is how each handler gets its dependencies without a global variable.
- `container.py` calls `build_tools(...)` once and gets the list of tools back.

### A handler, line by line
```python
async def get_portfolio(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    return await repo.get_portfolio(ctx.customer_id)
```
- Every handler gets two things: `ctx` (the context) and `args` (the checked arguments).
- It calls the repository with the customer id and returns a dictionary.
- The dictionary becomes JSON text for the model.

### ToolContext and customer_id
```python
@dataclass
class ToolContext:
    session: Session
    idempotency_key: str | None = None

    @property
    def customer_id(self) -> str:
        return self.session.require_customer_id()
```
- `ctx.customer_id` looks like a plain value, but it is a `@property`.
- It reads the customer from the session. If nobody is verified, it raises an error.
- The model never provides this id. That is the main protection against seeing other customers' data.

### verify_identity: the special one
```python
async def verify_identity(ctx, args):
    session = ctx.session
    if session.verified_customer_id is not None:
        raise ToolExecutionError("already_verified", "This session is already verified.")
    if await repo.verify_identity(args.customer_id, args.phone_last4):
        session.verified_customer_id = args.customer_id
        return {"verified": True}
    session.failed_verifications += 1
    ...
```
- It is the only tool that takes a customer id from the model, because that id is the claim being checked.
- On success it sets `session.verified_customer_id`. All other data tools depend on that.
- On failure it counts the attempt. After two failures it escalates.

### Registering a tool
```python
Tool(
    "get_portfolio",
    "Get the verified customer's holdings and total balance in NIS.",
    NoArgs,
    get_portfolio,
)
Tool("verify_identity", "...", VerifyIdentityArgs, verify_identity, requires_verification=False)
Tool("request_withdrawal", "...", WithdrawalArgs, request_withdrawal, access="write")
```
- The first four values are positional: name, description, argument class, handler.
- Extra settings are passed by name.
- `requires_verification=False` is needed for tools that must work before login, like verify and search.

### The ToolRegistry
```python
class ToolRegistry:
    def __init__(self, tools: list[Tool], *, timeout_s: float) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._timeout_s = timeout_s

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]
```
- It stores the tools in a dictionary: name to tool. This is a dictionary comprehension.
- `specs()` gives the model the list of descriptions on every call.
- `execute()` runs one tool call. That is the next card.

### The checks in order
```python
tool = self._tools.get(call.name)            # 1. does this tool exist?
args = tool.input_model.model_validate(...)  # 2. are the arguments valid?
if tool.requires_verification:
    session.require_customer_id()            # 3. is the customer verified?
if tool.access == "write":
    return await self._run_write(...)        # 4. is a write confirmed?
return await self._invoke(...)               # 5. run it, with timeout and retry
```
- Each check can stop the call with an error.
- The error goes back to the model as a normal result, so the chat continues.
- Nothing here depends on what the model says or promises.

### execute never crashes
```python
try:
    payload = await self._run(call, session)
    result = ToolResult(tool_call_id=call.id, content=_dump(payload))
except ToolExecutionError as exc:
    result = _error(call, exc.code, exc.message)
except IdentityNotVerified as exc:
    result = _error(call, "identity_not_verified", str(exc))
except Exception:
    log_event("tool_exception", logging.ERROR, exc_info=True, tool=call.name)
    result = _error(call, "internal_error", "The tool failed. Do not guess the data.")
```
- Known problems become clear error codes the model can understand.
- Unknown problems are logged with the full traceback, and the model gets a safe, short message.
- The `except` order matters. Python uses the first one that matches.

### Results are JSON text
```python
def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)
```
- The model reads text, so the dictionary is turned into a JSON string.
- `default=str` handles values JSON does not know, like dates.
- `ensure_ascii=False` keeps non-English letters readable.

### The error helper
```python
def _error(call, code, message):
    content = _dump({"error": {"code": code, "message": message}})
    return ToolResult(tool_call_id=call.id, content=content, is_error=True)
```
- Every error has the same shape: a code and a message.
- `is_error=True` lets the AI provider and our logs know it failed.
- `tool_call_id` links the result to the model's request.

### A validation message, decoded
```python
def _summarise(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
```
- It turns pydantic's error list into a short text, like `phone_last4: String should match pattern`.
- `e['loc']` is the path to the bad field. `'.'.join(...)` glues it with dots.
- The quotes inside the f-string are different on purpose, so Python can read it.

### The write tool: two steps
```python
if matches and pending.turn < session.turn:
    session.pending_action = None
    return await self._invoke(tool, ToolContext(session, pending.idempotency_key), args)
...
return {"status": "confirmation_required", "executed": False, ...}
```
- First call: only remember the request and return "confirmation required".
- Second call, on a later user turn, with the same arguments: run it.
- The idempotency key is made by the code with `uuid4()`. The model never sees it.

### The retry (_invoke)
```python
for attempt in range(2):
    try:
        async with asyncio.timeout(self._timeout_s):
            return await tool.handler(ctx, args)
    except (ToolExecutionError, IdentityNotVerified):
        raise
    except Exception:
        if attempt == 1:
            raise
        await asyncio.sleep(RETRY_BACKOFF_S)
```
- Expected errors (like "insufficient balance") are raised at once. Retrying would not help.
- Unexpected errors and timeouts get one more try after a short wait.
- It is safe even for writes, because the idempotency key stops duplicates.

### One full example, end to end
Customer is verified and asks: "What's my balance?"
- The model replies with a tool request: `get_portfolio` with no arguments.
- `ToolRegistry.execute` checks it, runs the handler, and the handler asks the repository, which runs SQL in Postgres.
- The result goes back as JSON. The model reads it and writes: "Your balance is 125,400 NIS."

### How to add a new tool
Example idea (not built): `get_account_fees`.
- Write an argument class (or reuse `NoArgs`).
- Write the handler inside `build_tools`, and call the repository method it needs. Add that method to the repository interface, the Postgres adapter and the fake.
- Add `Tool(...)` to the returned list, then add a test and an eval case.
- Nothing in `core/` changes.

### Quick check: can you answer these?
- Why does `get_portfolio` take no arguments?
- Which tools work before the customer is verified, and why?
- What does the model see for a tool: the code or the description?
- Why does `execute` catch `Exception` at the end?

---

## 20. How the model chooses tools (and where the loop is)

This part answers three questions: where is the loop, who decides which tool to use, and can tools be external APIs.

### Where is the reasoning loop?
```python
# core/agent.py, in Agent._loop
for _ in range(self._max_iterations):                        # at most 6 rounds
    history = [*session.messages, *new_messages]
    response = await self._timed_llm_call(history, stats)   # ask the model
    if not response.tool_calls:
        return response.text                                 # it answered: done
    new_messages.append(Message(role="assistant", ..., tool_calls=response.tool_calls))
    results = await self._run_tools(response.tool_calls, session, stats)
    new_messages.append(Message(role="user", tool_results=results))
```
- The loop is the method `_loop` in `core/agent.py`.
- `run_turn` calls it. `_timed_llm_call` and `_run_tools` are the two steps inside it.
- Our code only repeats: ask, run tools, send results back. The "thinking" happens inside the model.

### Does our code decide which tool to use?
- No. We have no `if` that picks a tool.
- The model decides, every time it is called.
- Our code only checks and runs what the model asked for.

### What the model looks at
- The system prompt (`domain/system_prompt.md`) and the customer's message.
- The 7 tool definitions: name, description and arguments.
- The conversation so far, including earlier tool results.

### How it decides, with examples
- "What's the early withdrawal fee?" fits the description of `search_knowledge` (fees, rules, products). So it asks for that tool.
- "What's my balance?" from an unverified customer: the prompt says data tools need verification. So it usually asks for the ID and calls no tool.
- "Withdraw 5,000" fits `request_withdrawal`. Its description says the first call only proposes.

### It is pattern matching, not a rule table
- The model was trained to produce either text or a structured tool request.
- It matches the wording of the request to the wording of the descriptions.
- Because of that, it can be wrong, and it can give different answers on different runs.

### What the model can and cannot do
- It can only pick from the 7 tools we sent. It cannot call any Python method it likes.
- The name it uses is the tool name, like `get_portfolio`. Our code finds the matching handler.
- Every request still goes through the checks in `core/tools.py`. A wrong choice gets stopped there.

### How we steer its choices
- **Tool names and descriptions.** This is the strongest control. Vague or similar descriptions cause wrong picks.
- **Prompt rules.** Example: "ask to confirm before a withdrawal".
- **Fewer tools.** Less to confuse.
- **Code gates.** They are the safety net when the model picks wrong or is tricked.

### Can we see why it chose a tool?
- We can see WHAT it chose: the `tool_call` log lines, or a breakpoint on `response.tool_calls`.
- We cannot see its inner reasoning. The code does not request or show it.
- We check its choices with the evals. Each case says which tools must or must not be called.

### Can a tool call an external API?
Yes. A tool is just a Python function. Inside it can do anything.
- Today our tools use a repository, which runs SQL on Postgres.
- In a real deployment the repository would call the client's REST or SOAP APIs instead.
- The model never knows the difference. It only sees the name, the description and the arguments.

### A sketch of an API-backed repository (not built)
```python
class ClientApiRepository:
    async def get_portfolio(self, customer_id: str) -> dict:
        response = await self._http.get(f"/accounts/{customer_id}/portfolio")
        response.raise_for_status()
        return response.json()
```
- It has the same methods as `PostgresRepository`.
- You swap it in `container.py`. The tools, the prompt and the agent do not change.
- `raise_for_status()` raises an error on a bad HTTP answer. The registry turns it into a clean error result.

### What changes with an external API
- **Speed and failures.** The network can be slow or fail. Timeouts, the retry and clean errors matter more.
- **Writes.** Prefer an API that accepts an idempotency key. If not, keep your own table to stop duplicates.
- **Credentials.** Use least privilege and read-only first. Keep them in a secrets manager, never in the prompt.
- **Customer id.** The call must use the verified customer's id from the session, never one from the model.
- **Results.** Return only what the model needs, not the whole API response.

### Quick check: can you answer these?
- Where in the code does the model "decide"? (Hint: not in our code.)
- What two things does the model read to pick a tool?
- What happens if it picks a tool wrongly or is tricked?
- What would you change to use a real client API?
