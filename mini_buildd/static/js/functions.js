function toggleLastBuilds()
{
		$('#mb_lb_click_me').click(
				function()
				{
						$('#mb_last_builds').toggle();
						$('#mb_last_builds').is(":visible") ?  $('#mb_lb_anchor').html("hide") : $('#mb_lb_anchor').html("show");
				}
		);
}


function toggleLastPackages()
{
		$('#mb_lp_click_me').click(
				function()
				{
						$('#mb_last_packages').toggle();
						$('#mb_last_packages').is(":visible") ?  $('#mb_lp_anchor').html("hide") : $('#mb_lp_anchor').html("show");
				}
		);
}


$(document).ready(
		function()
		{
				toggleLastBuilds();
				toggleLastPackages();
		}
);
