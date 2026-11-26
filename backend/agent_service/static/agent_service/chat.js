const form = document.querySelector("#question-form");
const questionInput = document.querySelector("#question");
const send = document.querySelector("#send");
const welcome = document.querySelector("#welcome");
const exchange = document.querySelector("#exchange");
const currentQuestion = document.querySelector("#current-question");
const pending = document.querySelector("#pending");
const pendingMessage = document.querySelector("#pending-message");
const answer = document.querySelector("#answer");
const errorMessage = document.querySelector("#error");
const sources = document.querySelector("#sources");
const sourceList = document.querySelector("#source-list");

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.dataset.question;
    questionInput.focus();
  });
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (send.disabled) return;

  const question = questionInput.value.trim();
  if (!question) {
    questionInput.value = "";
    questionInput.reportValidity();
    return;
  }

  const body = new FormData(form);
  body.set("question", question);
  send.disabled = true;
  questionInput.readOnly = true;
  welcome.hidden = true;
  exchange.hidden = false;
  currentQuestion.textContent = question;
  answer.textContent = "";
  errorMessage.hidden = true;
  sources.hidden = true;
  sourceList.replaceChildren();
  pending.hidden = false;
  pendingMessage.textContent = "Working on your question…";
  window.scrollTo(0, 0);

  const waitingMessage = window.setTimeout(() => {
    pendingMessage.textContent = "Still working. The local model can take a few minutes.";
  }, 15000);

  try {
    const response = await fetch(form.action, { method: "POST", body });
    const data = await response.json();
    if (!response.ok) {
      errorMessage.textContent = data.error;
      errorMessage.hidden = false;
      return;
    }

    answer.textContent = data.answer;
    for (const url of data.sources) {
      const link = document.createElement("a");
      link.href = url;
      link.textContent = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      const item = document.createElement("li");
      item.append(link);
      sourceList.append(item);
    }
    sources.hidden = sourceList.children.length === 0;
    questionInput.value = "";
  } catch {
    errorMessage.textContent = "Couldn’t get a reply. Reload RBI Desk if the problem continues.";
    errorMessage.hidden = false;
  } finally {
    window.clearTimeout(waitingMessage);
    pending.hidden = true;
    send.disabled = false;
    questionInput.readOnly = false;
  }
});
