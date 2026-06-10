"""
Check product variants in the database
"""
import os
import sys
import django

# Set UTF-8 encoding for stdout
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from products.models import Product, ProductVariant

def check_variants():
    """Check product variants in the database"""
    
    print("Checking products and their variants...")
    print("=" * 50)
    
    products = Product.objects.all()
    
    for product in products:
        print(f"\nProduct: {product.name} (SKU: {product.sku})")
        variants = ProductVariant.objects.filter(product=product, is_active=True)
        print(f"  Total variants: {variants.count()}")
        
        for variant in variants[:5]:  # Show first 5 variants
            color = variant.color.name if variant.color else 'No color'
            size = variant.size.name if variant.size else 'No size'
            print(f"    - {color} / {size} (SKU: {variant.variant_sku})")
        
        if variants.count() > 5:
            print(f"    ... and {variants.count() - 5} more")
    
    print("\n" + "=" * 50)
    print("Total products:", products.count())
    print("Total variants:", ProductVariant.objects.filter(is_active=True).count())

if __name__ == '__main__':
    check_variants()
