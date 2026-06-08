import { bindListPagination, bindPrototypeActions } from "../core/prototype.js";
import { bindLogoutAction } from "../core/utils.js";

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
