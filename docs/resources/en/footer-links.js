// Add privacy policy and terms of use links to the footer
document.addEventListener('DOMContentLoaded', function() {
    // Find the copyright element
    var copyright = document.querySelector('.rst-content p:contains("Conservation International")') ||
                   document.querySelector('p:contains("Conservation International")');
    
    if (!copyright) {
        // Try to find any copyright text
        var allParagraphs = document.querySelectorAll('p');
        for (var i = 0; i < allParagraphs.length; i++) {
            if (allParagraphs[i].textContent.includes('Conservation International')) {
                copyright = allParagraphs[i];
                break;
            }
        }
    }
    
    if (copyright) {
        // Add privacy policy and terms of use links
        var linkSeparator = document.createElement('span');
        linkSeparator.innerHTML = ' | ';
        
        var privacyLink = document.createElement('a');
        privacyLink.href = 'https://www.conservation.org/privacy';
        privacyLink.textContent = 'Privacy Policy';
        privacyLink.target = '_blank';
        
        var separator = document.createElement('span');
        separator.innerHTML = ' | ';
        
        var termsLink = document.createElement('a');
        termsLink.href = 'https://www.conservation.org/terms';
        termsLink.textContent = 'Terms of Use';
        termsLink.target = '_blank';
        
        copyright.appendChild(linkSeparator);
        copyright.appendChild(privacyLink);
        copyright.appendChild(separator);
        copyright.appendChild(termsLink);
    } else {
        // If no copyright found, add footer at the bottom of the page
        var footer = document.createElement('div');
        footer.style.cssText = 'text-align: center; margin-top: 20px; padding-top: 15px; border-top: 1px solid #e1e4e5; font-size: 0.9em; color: #777;';
        footer.innerHTML = '<a href="https://www.conservation.org/privacy" target="_blank">Privacy Policy</a> | <a href="https://www.conservation.org/terms" target="_blank">Terms of Use</a>';
        
        var content = document.querySelector('.rst-content') || document.body;
        content.appendChild(footer);
    }
});
