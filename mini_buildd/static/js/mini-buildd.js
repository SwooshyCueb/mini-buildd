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

// Make selection on a (multiple) select via a regex
// selectID: id of the 'select' element
// regexID : id of the input element with the regex in 'value'
function mbdSelectByRegex(selectID, regexID)
{
		var select = document.getElementById(selectID);
		var regex = document.getElementById(regexID).value;
		for (i=0; i < select.length; i++)
		{
				select[i].selected = select[i].text.match(regex);
		}
};
