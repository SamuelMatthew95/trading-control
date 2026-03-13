import Link from 'next/link';
import { useRouter } from 'next/router';

const NAV_ITEMS = [
  { label: 'STOCKS', href: '/stocks' },
  { label: 'OPTIONS', href: '/options' },
];

export default function TopNav() {
  const router = useRouter();

  return (
    <div className="bg-white rounded-lg shadow-sm mb-6">
      <nav className="flex space-x-8 px-6" aria-label="Primary">
        {NAV_ITEMS.map((item) => {
          const isActive = router.pathname === item.href || (item.href === '/stocks' && router.pathname === '/');
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
                isActive
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
