function openDeleteModal(button) {
  const projectId = button.dataset.projectId;
  const projectName = button.dataset.projectName;

  document.getElementById("delete-modal-project-name").textContent = projectName;
  document.getElementById("delete-modal-form").action = `/projects/${projectId}/delete`;
  document.getElementById("delete-modal").showModal();
}

function openDeleteEnvModal(button) {
  const projectId = button.dataset.projectId;
  const envId = button.dataset.envId;
  const envName = button.dataset.envName;

  document.getElementById("delete-env-modal-name").textContent = envName;
  document.getElementById("delete-env-modal-form").action = `/projects/${projectId}/environments/${envId}/delete`;
  document.getElementById("delete-env-modal").showModal();
}

const SCENARIO_STEP_FIELDS = {
  navigate: ["path"],
  click: ["selector"],
  fill: ["selector", "value"],
  select_option: ["selector", "value"],
  wait: ["wait_ms"],
  assert_text: ["value"],
  assert_no_text: ["value"],
  assert_element: ["selector"],
  assert_count: ["selector", "operator", "count"],
  screenshot: [],
  save_value: ["selector", "value"],
  compare_values: ["value", "value2", "operator"],
};

function updateScenarioStepFields() {
  const select = document.getElementById("step_type");
  if (!select) return;
  const activeFields = SCENARIO_STEP_FIELDS[select.value] || [];
  document.querySelectorAll("[data-step-field]").forEach((el) => {
    el.classList.toggle("hidden", !activeFields.includes(el.dataset.stepField));
  });
}

document.addEventListener("DOMContentLoaded", updateScenarioStepFields);

function openAddStepModal() {
  const form = document.getElementById("step-form");
  form.reset();
  form.action = form.dataset.createUrl;
  document.getElementById("step-modal-title").textContent = "Adım Ekle";
  document.getElementById("step-submit-button").textContent = "Ekle";
  updateScenarioStepFields();
  document.getElementById("add-step-modal").showModal();
}

function openEditStepModal(button) {
  const form = document.getElementById("step-form");
  form.reset();
  form.action = button.dataset.editUrl;
  document.getElementById("step-modal-title").textContent = "Adımı Düzenle";
  document.getElementById("step-submit-button").textContent = "Kaydet";

  document.getElementById("step_type").value = button.dataset.stepType || "navigate";
  document.getElementById("path").value = button.dataset.path || "";
  document.getElementById("selector").value = button.dataset.selector || "";
  document.getElementById("value").value = button.dataset.value || "";
  document.getElementById("value2").value = button.dataset.value2 || "";
  if (button.dataset.operator) {
    document.getElementById("operator").value = button.dataset.operator;
  }
  document.getElementById("count").value = button.dataset.count || "";
  document.getElementById("wait_ms").value = button.dataset.waitMs || "";

  updateScenarioStepFields();
  document.getElementById("add-step-modal").showModal();
}
