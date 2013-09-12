// Toggle a element on/off
// elName    : id of the element to toggle
// textElName: id of the element with the toggle action text (show, hide)
function mbdToggleElement(elName, textElName, hideText, showText)
{
		var el = document.getElementById(elName);
		var textEl = document.getElementById(textElName);
		if (el.style.display == "block")
		{
				// Toggle to "show"
				textEl.innerHTML = showText
				el.style.display = "none";
		}
		else
		{
				// Toggle to "hide"
				textEl.innerHTML = hideText
				el.style.display = "block";
		}
};
