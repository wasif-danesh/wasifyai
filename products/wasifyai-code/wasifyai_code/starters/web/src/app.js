import { greeting } from "./logic.js";

document.querySelector("#greeting").textContent = greeting(new Date());
